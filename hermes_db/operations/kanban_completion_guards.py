"""Completion evidence is scoped, audited and never replaced with a silent no-op."""

from sqlalchemy import select

from hermes_db.repositories import kanban as repo
from hermes_db.tables.kanban import tasks
from hermes_db.core.values import decode_text, encode_text


def verify_on_connection(conn, store, task_id, claimed_ids):
    ordered = list(dict.fromkeys(str(value).strip() for value in claimed_ids if str(value).strip()))
    task = repo.get(conn, store, task_id)
    if task is None:
        return [], ordered
    found = {decode_text(tid): decode_text(creator) for tid, creator in conn.execute(select(tasks.c.id, tasks.c.created_by)
        .where(repo.scope(tasks, store), tasks.c.id.in_([encode_text(value) for value in ordered])))}
    children = set(repo.linked_ids(conn, store, task_id, parents=False))
    verified, phantom = [], []
    for tid in ordered:
        creator = found.get(tid)
        trusted = creator is not None and ((task["assignee"] and creator == task["assignee"]) or creator == task_id or tid in children)
        (verified if trusted else phantom).append(tid)
    return verified, phantom


def _verify_created_cards(store, completing_task_id, claimed_ids):
    with store.read() as conn:
        return verify_on_connection(conn, store, completing_task_id, claimed_ids or ())


def _audit(conn, store, task_id, kind, payload, error):
    from hermes_db.operations.kanban_command_receipts import refusal
    if repo.get(conn, store, task_id) is not None:
        repo.event(conn, store, task_id, kind, payload)
    store.command_result(conn, refusal(error))


def _gate_created_cards(store, task_id, created_cards, preview_text):
    from hermes_cli import kanban_db as kb
    if not created_cards:
        return []
    with store.write() as conn:
        verified, phantom = verify_on_connection(conn, store, task_id, created_cards)
        if phantom:
            error = kb.HallucinatedCardsError(phantom, task_id)
            _audit(conn, store, task_id, "completion_blocked_hallucination", {"phantom_cards": phantom,
                "verified_cards": verified, "summary_preview": kb._first_line(preview_text, 200) or None}, error)
    if phantom:
        raise error
    return verified


def _gate_empty_completion(store, task_id, *, result, summary):
    from hermes_cli import kanban_db as kb
    with store.write() as conn:
        row = repo.get(conn, store, task_id)
        if row is None or row["status"] == "review":
            return
        if any(kb._substantive_text(value) for value in (result, summary, row["result"])):
            return
        error = kb.EmptyCompletionError(task_id)
        _audit(conn, store, task_id, "completion_blocked_empty_result", {"result_preview": kb._first_line(result, 200) or None,
            "summary_preview": kb._first_line(summary, 200) or None}, error)
    raise error


def _phantom_ids(conn, store, text):
    from hermes_cli.kanban_db import _TASK_ID_PROSE_RE
    ids = list(dict.fromkeys(_TASK_ID_PROSE_RE.findall(text or "")))
    found = {decode_text(tid) for tid in conn.scalars(select(tasks.c.id).where(repo.scope(tasks, store),
             tasks.c.id.in_([encode_text(value) for value in ids])))}
    return [tid for tid in ids if tid not in found]


def _scan_prose_for_phantom_ids(store, text):
    with store.read() as conn:
        return _phantom_ids(conn, store, text)


def _flag_phantom_prose_refs(store, task_id, run_id, summary, result, verified_cards):
    import json
    from hermes_db.tables.kanban import events
    text = " ".join(value for value in (summary, result) if value)
    if not text:
        return
    with store.write() as conn:
        phantom = [value for value in _phantom_ids(conn, store, text) if value not in set(verified_cards)]
        if not phantom:
            return
        payload = {"phantom_refs": phantom, "source": "completion_summary"}
        kind = "suspected_hallucinated_references"
        existing = conn.scalar(select(events.c.id).where(repo.key(store, task_id, events),
            events.c.run_id == run_id, events.c.kind == encode_text(kind),
            events.c.payload == encode_text(json.dumps(payload, ensure_ascii=False))).limit(1))
        if existing is None:
            repo.event(conn, store, task_id, kind, payload, run_id)
