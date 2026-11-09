"""Atomic compaction: version proof, archive, carry and counters in one commit."""

from copy import deepcopy
import time

from sqlalchemy import select

from hermes_db.compression_coverage import Coverage
from hermes_db.operations import messages as writes, transcript_guards
from hermes_db.repositories import compression as repo, leases, messages, sessions
from hermes_db.tables.conversations import messages as table
from hermes_db.tables.gateway import compression_locks
from hermes_db.core.values import encode_config, model_config


def require_lease(conn, scope, session_id, holder, *, error_type, refresh=False, ttl=300):
    if refresh and holder:
        leases.renew(conn, scope, compression_locks, "session_id", session_id, holder, time.time() + ttl)
    row = conn.execute(select(compression_locks).where(
        *leases.where(scope, compression_locks, "session_id", session_id)).with_for_update()).mappings().one_or_none()
    if row is None or not holder or row["holder"] != holder or row["expires_at"] <= time.time():
        raise error_type("Compression lease lost before publication")


def compact(transactions, scope, session_id, batch, **options):
    writes._stamp_logical_identities(batch)
    work = deepcopy(batch)
    with transactions.write() as conn:
        count = compact_on_connection(conn, scope, session_id, work, **options)
    writes._publish_stamps(batch, work)
    return count


def compact_on_connection(conn, scope, session_id, batch, *, model_config_patch=None, watermark=None,
        lock_holder=None, tail_count=0, carried_messages=None, covered_ids=None, unresolved_held=None, held_for_cas=None):
    from hermes_state_errors import HeldRowRewrittenError, SessionCompressionInProgressError

    session = transcript_guards.check(conn, scope, session_id)
    if lock_holder is not None:
        require_lease(conn, scope, session_id, lock_holder, error_type=SessionCompressionInProgressError)
    active = messages.select_rows(conn, scope, [session_id], table.c.active == 1)
    coverage = Coverage(active)
    if held_for_cas and coverage.mismatches(held_for_cas):
        raise HeldRowRewrittenError("A held row was rewritten before compaction committed")
    clone_ids, rewind_ids = _classify(coverage, batch, watermark, tail_count, carried_messages,
                                    covered_ids, unresolved_held)
    repo.archive(conn, scope, session_id, rewind_ids)
    inserted, tools = writes.insert_rows(conn, scope, session_id, batch)
    repo.clone_rows(conn, scope, session_id, clone_ids)
    from hermes_state_messages import _tool_calls_len
    tools += sum(_tool_calls_len(coverage.by_id[rid]["tool_calls"]) for rid in clone_ids)
    count = inserted + len(clone_ids)
    values = {"message_count": count, "tool_call_count": tools}
    if model_config_patch is not None:
        config = model_config(session["model_config"])
        for key, value in model_config_patch.items():
            if value is None:
                config.pop(key, None)
            else:
                config[key] = value
        values["model_config"] = encode_config(config)
    sessions.update_session(conn, scope, session_id, values)
    messages.reconcile_orders(conn, scope, session_id)
    messages.bump_revision(conn, scope, session_id)
    return count


def _classify(coverage, batch, watermark, tail_count, carried_messages, covered_ids, unresolved_held):
    active_ids = list(coverage.by_id)
    proved = coverage._proved_coverage(None, None, covered_ids, unresolved_held, watermark)
    carried_ids = coverage.carried_originals(carried_messages or [])
    if proved is not None:
        covered = set(proved[0]) | set(carried_ids)
        tail_ids = [rid for rid in active_ids if rid not in covered]
        below = [rid for rid in active_ids if rid in covered]
    else:
        tail_ids = [rid for rid in active_ids if watermark is not None and rid > int(watermark)]
        below = [rid for rid in active_ids if watermark is None or rid <= int(watermark)]
    carried, weak = coverage.carried_tail(tail_ids, batch)
    tail_below = tail_count - coverage._carried_tail_slots(carried, len(batch), tail_count)
    rewind = list(carried_ids)
    if tail_below > 0:
        if proved is not None:
            rewind += coverage._tail_originals(below, tail_below, proved[1])
        else:
            width = int(tail_below) + coverage._uncounted_merged_rows(batch[-int(tail_count):])
            rewind += below[-width:]
    rewind += [rid for rid in tail_ids if rid not in weak]
    return [rid for rid in tail_ids if rid not in carried], list(dict.fromkeys(rewind))
