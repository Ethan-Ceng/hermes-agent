"""SessionLifecycle: explicit scoped session lifecycle operations sharing one resource context."""
from __future__ import annotations
from typing import Any, Optional
import logging
import time
from hermes_db.errors import StorageBusyError
from hermes_db.domains.sessions.postgres.operations import leases, housekeeping, gateway, gateway_peers as operations
from hermes_db.domains.sessions.postgres.queries import retirement, retirement_housekeeping, sessions as housekeeping_sessions, retention, sessions as handoffs_sessions, gateway as gateway_repo, gateway_peers as gateway_peers_repo, sessions as gateway_peers_sessions
from sqlalchemy import func, select, or_
from hermes_db.integration.postgres.operations import maintenance
from hermes_db.tables.conversations import sessions as maintenance_sessions, sessions as table, messages, sessions as health_sessions
from sqlalchemy.dialects.postgresql import insert
from hermes_db.tables.gateway import gateway_heartbeats as heartbeats, gateway_hygiene_state as hygiene
from hermes_db.core.values import decode_text, encode_text
import json
from hermes_db.domains.sessions.rules import session_gateway_runtime
from hermes_db.domains.sessions.postgres.queries.archive_refs import referenced_names
logger = logging.getLogger(__name__)

class SessionLifecycle:

    def __init__(self, context, flush_for_read):
        self._context = context
        self._flush_for_read = flush_for_read

    def _change_lease(self, session_id, holder, action, *, turn=False, ttl_seconds=300, patience_s=None):
        self._context.assert_open()
        if not session_id or not holder:
            return False if action != 'release' else None
        now = time.time()
        with self._context.transactions.write(lock_timeout=patience_s) as conn:
            return leases.change(conn, self._context.scope, session_id, holder, action, turn=turn, ttl_seconds=ttl_seconds, now=now)

    def try_acquire_compression_lock(self, session_id, holder, ttl_seconds=300.0):
        return self._change_lease(session_id, holder, 'acquire', ttl_seconds=ttl_seconds)

    def refresh_compression_lock(self, session_id, holder, ttl_seconds=300.0):
        return self._change_lease(session_id, holder, 'renew', ttl_seconds=ttl_seconds)

    def release_compression_lock(self, session_id, holder):
        self._change_lease(session_id, holder, 'release')

    def get_compression_lock_holder(self, session_id):
        with self._context.read() as conn:
            return leases.compression_holder(conn, self._context.scope, session_id) if session_id else None

    def try_acquire_session_turn_lease(self, session_id, holder, *, ttl_seconds=300.0, patience_s=None):
        return self._change_lease(session_id, holder, 'acquire', turn=True, ttl_seconds=ttl_seconds, patience_s=patience_s)

    def refresh_session_turn_lease(self, session_id, holder, *, ttl_seconds=300.0, patience_s=None):
        return self._change_lease(session_id, holder, 'renew', turn=True, ttl_seconds=ttl_seconds, patience_s=patience_s)

    def release_session_turn_lease(self, session_id, holder):
        self._change_lease(session_id, holder, 'release', turn=True)

    def session_turn_lease_expires_at(self, session_id, holder):
        with self._context.read() as conn:
            return leases.expiry(conn, self._context.scope, session_id, holder) if session_id and holder else None

    def _session_turn_lease_key(self, session_id):
        from hermes_db.domains.sessions.postgres.queries import sessions
        with self._context.read() as conn:
            row = sessions.raw_session(conn, self._context.scope, session_id)
            return row['lineage_root_id'] if row else session_id

    def _lease_callback(self, callback, *args):
        if callback is None:
            return None
        try:
            with self._context.profile.activate():
                return callback(*args)
        except Exception:
            logger.debug('Session lease callback failed', exc_info=True)
        return None

    def acquire_session_turn_lease(self, session_id, holder, *, ttl_seconds=300.0, wait_seconds=1800.0, poll_interval_seconds=1.0, on_wait=None, wait_notice_interval_seconds=15.0, should_abort=None, acquire_patience_s=0.5, on_contended=None):
        deadline = time.monotonic() + max(0.0, float(wait_seconds))
        patience, started, last_notice = (acquire_patience_s, None, None)
        while True:
            self._context.assert_open()
            if self._lease_callback(should_abort):
                return False
            try:
                if self.try_acquire_session_turn_lease(session_id, holder, ttl_seconds=ttl_seconds, patience_s=patience):
                    return True
            except StorageBusyError:
                self._lease_callback(on_contended)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                patience = min(acquire_patience_s + max(0.01, float(poll_interval_seconds)), remaining)
                continue
            patience = acquire_patience_s
            now = time.monotonic()
            if now >= deadline:
                return False
            started = now if started is None else started
            if last_notice is None or now - last_notice >= max(0.0, float(wait_notice_interval_seconds)):
                self._lease_callback(on_wait, max(0.0, now - started))
                last_notice = now
            time.sleep(min(max(0.01, float(poll_interval_seconds)), deadline - now))

    def delete_session(self, session_id, sessions_dir=None, expected_delete_ids=None, expected_display_messages=None, exclude_active_write_guards=False, include_compression_chain=False):
        from hermes_db.domains.sessions.postgres.operations import retirement as operations
        if include_compression_chain:
            return self.delete_sessions([session_id], sessions_dir=sessions_dir, exclude_active_write_guards=exclude_active_write_guards, include_compression_chain=True) > 0
        with self._context.write() as conn:
            deleted, targets = operations.delete_one(conn, self._context.scope, session_id, expected_delete_ids=expected_delete_ids, expected_display_messages=expected_display_messages, exclude_active_write_guards=exclude_active_write_guards)
        if deleted:
            self._after_session_delete(targets, primary=session_id, sessions_dir=sessions_dir)
        return deleted

    def delete_sessions(self, session_ids, sessions_dir=None, exclude_active_write_guards=False, skipped_ids=None, include_compression_chain=False):
        from hermes_db.domains.sessions.postgres.operations import retirement as operations
        with self._context.write() as conn:
            count, targets, skipped = operations.delete_many(conn, self._context.scope, session_ids, exclude_active_write_guards=exclude_active_write_guards, include_compression_chain=include_compression_chain)
        if skipped_ids is not None:
            skipped_ids.extend(skipped)
        if count:
            self._after_session_delete(targets, primary=session_ids[0] if len(session_ids) == 1 else None, sessions_dir=sessions_dir)
        return count

    def _after_session_delete(self, targets, *, primary=None, reason='delete', sessions_dir=None):
        from hermes_db.integration.events import emit_deleted
        from hermes_db.domains.sessions.postgres.support.retired_files import remove
        emit_deleted(self._context.profile, targets, reason=reason, primary=primary)
        remove(sessions_dir, targets)
        self.collect_retired_media()

    def collect_retired_media(self):
        from hermes_db.domains.sessions.postgres.support.retired_media import collect
        collect(self._context)

    def _export_limit(self, maximum):
        self._context.assert_open()
        if maximum is None:
            from hermes_state import resolved_max_export_messages
            with self._context.profile.activate():
                maximum = resolved_max_export_messages()
        return maximum

    def assert_export_safe(self, session_id, max_messages=None):
        from hermes_state import SessionExportTooLargeError
        maximum = self._export_limit(max_messages)
        if maximum < 0:
            raise ValueError('max_messages must be non-negative')
        if maximum == 0:
            return 0
        with self._context.read() as conn:
            count = retirement.export_count(conn, self._context.scope, session_id, maximum)
        if count > maximum:
            raise SessionExportTooLargeError(session_id, count, maximum)
        return count

    def assert_exports_safe(self, session_ids, max_messages=None):
        maximum = self._export_limit(max_messages)
        if maximum == 0:
            return
        for session_id in session_ids:
            self.assert_export_safe(session_id, max_messages=maximum)

    def get_session_delete_targets(self, session_id):
        with self._context.read() as conn:
            return retirement.native_targets(conn, self._context.scope, session_id)

    def session_is_empty(self, session_id):
        from sqlalchemy import select
        from hermes_db.tables.conversations import sessions as table
        with self._context.read() as conn:
            child = table.alias('child')
            has_child = select(child.c.id).where(child.c.store_id == self._context.scope.require_store_id(), child.c.parent_session_id == table.c.id).exists()
            return conn.scalar(select(table.c.id).where(table.c.store_id == self._context.scope.require_store_id(), table.c.id == session_id, table.c.title.is_(None), ~housekeeping._has_messages(self._context.scope), ~has_child)) is not None

    def prune_empty_ghost_sessions(self, sessions_dir=None):
        with self._context.write() as conn:
            ids = housekeeping.prune_ghosts(conn, self._context.scope)
        self._after_session_delete(ids, reason='ghost_prune', sessions_dir=sessions_dir)
        return len(ids)

    def delete_empty_sessions(self, sessions_dir=None):
        with self._context.write() as conn:
            ids = housekeeping.delete_empty(conn, self._context.scope)
        if ids:
            self._after_session_delete(ids, reason='empty_sweep', sessions_dir=sessions_dir)
        else:
            self.collect_retired_media()
        return len(ids)

    def delete_session_if_empty(self, session_id, sessions_dir=None):
        with self._context.write() as conn:
            deleted = housekeeping.delete_if_empty(conn, self._context.scope, session_id)
        if deleted:
            self._after_session_delete([session_id], reason='empty_sweep', sessions_dir=sessions_dir)
        else:
            self.collect_retired_media()
        return deleted

    def discard_unadmitted_session(self, session_id):
        with self._context.write() as conn:
            deleted, fenced = housekeeping.discard_unadmitted(conn, self._context.scope, session_id)
        if fenced:
            self._after_session_delete(fenced, primary=session_id)
        return deleted

    def prune_never_active_keyed_sessions(self, *, older_than_days, sessions_dir=None, deleted_ids=None):
        with self._context.write() as conn:
            count, removed, skipped, routes, reported = housekeeping.never_active(conn, self._context.scope, older_than_days)
        if removed:
            self._after_session_delete(removed, sessions_dir=sessions_dir)
        if deleted_ids is not None:
            deleted_ids.extend(reported)
        return (count, routes, len(skipped))

    def prune_retired_tombstones(self, older_than=604800):
        with self._context.write() as conn:
            housekeeping_sessions.lock_store(conn, self._context.scope, exclusive=True)
            retirement_housekeeping.prune(conn, self._context.scope, older_than)

    def retired_session(self, session_id):
        with self._context.read() as conn:
            return housekeeping_sessions.retired_session(conn, self._context.scope, session_id)

    def create_conflict(self, session_id):
        with self._context.read() as conn:
            if housekeeping_sessions.raw_session(conn, self._context.scope, session_id) is not None:
                return ('session_exists', 'Session already exists')
            if housekeeping_sessions.retired_session(conn, self._context.scope, session_id):
                return ('session_deleted', 'Session was deleted; its id cannot be reused')
        return None

    def has_mutation_receipt(self, principal_id, session_id, request_id):
        with self._context.read() as conn:
            return retirement_housekeeping.has_receipt(conn, self._context.scope, principal_id, session_id, request_id)

    def first_generation(self, derive, *, pinned=None, spent=None):
        from hermes_db.domains.runtime.postgres.operations.effects import invoke
        generation = 0
        with self._context.profile.activate(), self._context.read() as conn:
            while True:
                sid = derive(generation)
                if housekeeping_sessions.retired_session(conn, self._context.scope, sid):
                    if invoke(pinned, conn, self._context.scope, sid):
                        return (generation, sid)
                elif spent is None or not invoke(spent, conn, self._context.scope, sid):
                    return (generation, sid)
                generation += 1

    def keep_passed_fences(self, derive, session_id):
        with self._context.profile.activate(), self._context.write() as conn:
            housekeeping_sessions.lock_store(conn, self._context.scope, exclusive=True)
            return retirement_housekeeping.keep_passed(conn, self._context.scope, derive, session_id)

    def list_prune_candidates(self, older_than_days=None, source=None, *, whole_lineages=False, **filters):
        with self._context.read() as conn:
            return retention.candidates(conn, self._context.scope, older_than_days, source, whole_lineages=whole_lineages, **filters)

    def count_prune_matches(self, older_than_days=None, source=None, *, pinned_only=False, **filters):
        if pinned_only:
            filters['include_pinned'] = True
        with self._context.read() as conn:
            clauses = retention.conditions(conn, self._context.scope, older_than_days, source, filters)
            if pinned_only:
                clauses.append(maintenance_sessions.c.pinned != 0)
            return conn.scalar(select(func.count()).select_from(maintenance_sessions).where(*clauses))

    def count_open_prune_matches(self, older_than_days=None, source=None, **filters):
        if filters.get('include_open'):
            return 0
        with self._context.read() as conn:
            return conn.scalar(select(func.count()).select_from(maintenance_sessions).where(*retention.conditions(conn, self._context.scope, older_than_days, source, filters, only_open=True)))

    def archive_sessions(self, older_than_days=None, source=None, **filters):
        filters.setdefault('archived', False)
        filters['lineage_tips_only'] = True
        with self._context.write() as conn:
            count, events = maintenance.archive(conn, self._context.scope, older_than_days, source, filters)
        self._emit_archives(events)
        return count

    def _emit_archives(self, events):
        from hermes_db.integration.events import emit_deleted
        for primary, ids in events:
            emit_deleted(self._context.profile, ids, reason='archive', primary=primary)

    def prune_sessions(self, older_than_days=90, source=None, sessions_dir=None, exclude_active_write_guards=False, deleted_ids=None, **filters):
        if filters.get('include_open'):
            raise ValueError('prune_sessions never deletes open sessions')
        with self._context.write() as conn:
            removed = maintenance.prune(conn, self._context.scope, older_than_days, source, filters, exclude_active_write_guards=exclude_active_write_guards)
        if deleted_ids is not None:
            deleted_ids.extend(removed)
        if removed:
            self._after_session_delete(removed, reason='prune', sessions_dir=sessions_dir)
        else:
            self.collect_retired_media()
        return len(removed)

    def archive_stale_sessions(self, idle_days, *, exclude_pinned=True):
        if idle_days is None or idle_days < 0:
            return 0
        with self._context.write() as conn:
            count, events = maintenance.stale_archive(conn, self._context.scope, idle_days, exclude_pinned)
        self._emit_archives(events)
        return count

    def maybe_auto_archive(self, idle_days=3, min_interval_hours=24, exclude_pinned=True):
        try:
            with self._context.write() as conn:
                result, events = maintenance.throttled_archive(conn, self._context.scope, idle_days, exclude_pinned, min_interval_hours)
            self._emit_archives(events)
            return result
        except Exception as error:  # health: allow BLE001 -- automatic optional maintenance never fails startup
            logger.warning('PG auto-archive deferred (%s)', type(error).__name__)
            return {'skipped': False, 'archived': 0, 'error': type(error).__name__}

    def sweep_orphaned_sessions(self, **options):
        with self._context.write() as conn:
            return maintenance.sweep_orphans(conn, self._context.scope, **options)

    def maybe_auto_prune_and_vacuum(self, retention_days=90, min_interval_hours=24, vacuum=True, sessions_dir=None, min_vacuum_interval_days=30, min_vacuum_freelist_ratio=0.25):
        # Instance operators own physical PG maintenance; legacy arguments only select data cleanup.
        if retention_days is None or retention_days < 0:
            return {'skipped': True, 'pruned': 0, 'closed': 0, 'vacuumed': False}
        try:
            with self._context.write() as conn:
                result, removed = maintenance.auto_prune(conn, self._context.scope, retention_days, min_interval_hours)
            if removed:
                self._after_session_delete(removed, reason='prune', sessions_dir=sessions_dir)
            return result
        except Exception as error:  # health: allow BLE001 -- automatic optional maintenance never fails startup
            logger.warning('PG auto-prune deferred (%s)', type(error).__name__)
            return {'skipped': False, 'pruned': 0, 'closed': 0, 'vacuumed': False, 'error': type(error).__name__}

    def register_backend_heartbeat(self, *, backend_id, pid, started_at, last_heartbeat=None, profile='', host=''):
        with self._context.write() as conn:
            if not backend_id:
                return
            statement = insert(heartbeats).values(store_id=self._context.scope.require_store_id(), backend_id=str(backend_id), pid=int(pid), started_at=float(started_at), last_heartbeat=time.time() if last_heartbeat is None else float(last_heartbeat), profile=str(profile), host=str(host))
            fields = ('pid', 'started_at', 'last_heartbeat', 'profile', 'host')
            conn.execute(statement.on_conflict_do_update(index_elements=list(heartbeats.primary_key.columns), set_={field: statement.excluded[field] for field in fields}))

    def clear_backend_heartbeat(self, backend_id):
        with self._context.write() as conn:
            return bool(backend_id) and conn.execute(heartbeats.delete().where(heartbeats.c.store_id == self._context.scope.require_store_id(), heartbeats.c.backend_id == str(backend_id))).rowcount > 0

    def prune_stale_heartbeats(self, *, max_age_seconds):
        with self._context.write() as conn:
            if max_age_seconds <= 0:
                return []
            return list(conn.execute(heartbeats.delete().where(heartbeats.c.store_id == self._context.scope.require_store_id(), heartbeats.c.last_heartbeat < time.time() - max_age_seconds).returning(heartbeats.c.backend_id)).scalars())

    def list_backend_heartbeats(self):
        fields = ('backend_id', 'pid', 'started_at', 'last_heartbeat', 'profile', 'host')
        with self._context.read() as conn:
            return [dict(row) for row in conn.execute(select(*(heartbeats.c[field] for field in fields)).where(heartbeats.c.store_id == self._context.scope.require_store_id()).order_by(heartbeats.c.last_heartbeat.desc())).mappings()]

    def increment_hygiene_failure_streak(self, session_key):
        with self._context.write() as conn:
            if not session_key:
                return 1
            statement = insert(hygiene).values(store_id=self._context.scope.require_store_id(), session_key=session_key, failure_streak=1)
            return conn.scalar(statement.on_conflict_do_update(index_elements=list(hygiene.primary_key.columns), set_={'failure_streak': hygiene.c.failure_streak + 1}).returning(hygiene.c.failure_streak))

    def reset_hygiene_failure_streak(self, session_key):
        with self._context.write() as conn:
            if session_key:
                conn.execute(hygiene.delete().where(hygiene.c.store_id == self._context.scope.require_store_id(), hygiene.c.session_key == session_key))

    def _handoff_update(self, session_id, values, *conditions):
        with self._context.write() as conn:
            if handoffs_sessions.lock_session(conn, self._context.scope, session_id) is None:
                return False
            return handoffs_sessions.update_session(conn, self._context.scope, session_id, values, *conditions) > 0

    def request_handoff(self, session_id, platform):
        return self._handoff_update(session_id, {'handoff_state': 'pending', 'handoff_platform': platform, 'handoff_error': None}, or_(table.c.handoff_state.is_(None), table.c.handoff_state.in_(('completed', 'failed'))))

    def get_handoff_state(self, session_id):
        with self._context.read() as conn:
            row = handoffs_sessions.raw_session(conn, self._context.scope, session_id)
            return {'state': row['handoff_state'], 'platform': row['handoff_platform'], 'error': decode_text(row['handoff_error'])} if row else None

    def list_pending_handoffs(self):
        with self._context.read() as conn:
            ids = conn.execute(select(table.c.id).where(table.c.store_id == self._context.scope.require_store_id(), table.c.handoff_state == 'pending').order_by(table.c.started_at)).scalars().all()
            rows = handoffs_sessions.get_sessions(conn, self._context.scope, ids)
            return [rows[sid] for sid in ids]

    def claim_handoff(self, session_id):
        return self._handoff_update(session_id, {'handoff_state': 'running'}, table.c.handoff_state == 'pending')

    def has_pending_handoffs(self):
        with self._context.read() as conn:
            return conn.scalar(select(table.c.id).where(table.c.store_id == self._context.scope.require_store_id(), table.c.handoff_state == 'pending').limit(1)) is not None

    def complete_handoff(self, session_id):
        self._handoff_update(session_id, {'handoff_state': 'completed', 'handoff_error': None})

    def fail_handoff(self, session_id, error, *, only_states=None):
        conditions = [table.c.handoff_state.in_(only_states)] if only_states else []
        return self._handoff_update(session_id, {'handoff_state': 'failed', 'handoff_error': encode_text(error[:500])}, *conditions)

    def reclaim_stale_running_handoffs(self, error):
        with self._context.write() as conn:
            handoffs_sessions.lock_store(conn, self._context.scope, exclusive=True)
            rows = conn.execute(select(table).where(table.c.store_id == self._context.scope.require_store_id(), table.c.handoff_state == 'running')).mappings().all()
            for root in sorted({row['lineage_root_id'] for row in rows}):
                handoffs_sessions.lock_root(conn, self._context.scope, root)
            ids = [row['id'] for row in rows]
            if ids:
                conn.execute(table.update().where(table.c.store_id == self._context.scope.require_store_id(), table.c.id.in_(ids)).values(handoff_state='failed', handoff_error=encode_text(error[:500])))
            return ids

    @staticmethod
    def session_gateway_runtime(session_meta: Optional[dict[str, Any]]) -> dict[str, Any]:
        return session_gateway_runtime(session_meta)

    def purge_profile_state(self, profile):
        from hermes_db.integration.postgres.operations.profile_purge import purge
        with self._context.write() as conn:
            return purge(conn, self._context.scope, profile)

    def rekey_profile_state(self, old_name, new_name):
        from hermes_db.domains.sessions.postgres.operations.gateway_rekey import rekey
        with self._context.write() as conn:
            return rekey(conn, self._context.scope, old_name, new_name)

    def save_gateway_routing_entry(self, session_key, entry_json, *, scope=''):
        with self._context.write() as conn:
            if session_key and entry_json:
                gateway.save_route(conn, self._context.scope, session_key, entry_json, namespace=scope)

    def replace_gateway_routing_entries(self, entries, *, scope=''):
        with self._context.write() as conn:
            return gateway.replace_routes(conn, self._context.scope, entries, namespace=scope)

    def load_gateway_routing_entries(self, *, scope=''):
        with self._context.read() as conn:
            return {row['session_key']: row['entry_json'] for row in gateway_repo.routing_rows(conn, self._context.scope, scope)}

    def gateway_routing_entry_for_session(self, session_id):
        with self._context.read() as conn:
            for row in gateway_repo.routing_rows(conn, self._context.scope):
                try:
                    entry = json.loads(row['entry_json'])
                except (ValueError, TypeError, RecursionError):
                    continue
                if isinstance(entry, dict) and entry.get('session_id') == session_id:
                    return entry
        return None

    def retire_gateway_routes(self, session_ids, *, namespace, expiring=()):
        ids = sorted({str(sid) for sid in session_ids if sid})
        with self._context.write() as conn:
            if ids:
                gateway.retire_routes(conn, self._context.scope, ids, namespace=namespace, expiring=expiring)
    _ORPHAN_ADOPTION_MAX_GAP_S = 900.0

    def record_gateway_session_peer(self, session_id, *, source, user_id=None, session_key=None, chat_id=None, chat_type=None, thread_id=None, display_name=None, origin_json=None, include_compression_ancestors=False, transport_profile=None):
        with self._context.write() as conn:
            if session_id and session_key:
                operations.record(conn, self._context.scope, session_id, source=source, own_profile=self._context.own_profile, include_compression_ancestors=include_compression_ancestors, user_id=user_id, session_key=session_key, chat_id=chat_id, chat_type=chat_type, thread_id=thread_id, display_name=display_name, origin_json=origin_json, transport_profile=transport_profile)

    def list_gateway_sessions(self, *, platform=None, active_only=True):
        self._flush_for_read()
        with self._context.read() as conn:
            ids = gateway_peers_repo.newest_ids(conn, self._context.scope, platform=platform, active_only=active_only)
            rows = gateway_peers_sessions.get_sessions(conn, self._context.scope, ids)
            from hermes_db.domains.sessions.postgres.queries.session_queries import last_activity
            from hermes_db.tables.conversations import sessions as table
            from sqlalchemy import select
            activity = dict(conn.execute(select(table.c.id, last_activity(conn)).where(table.c.store_id == self._context.scope.require_store_id(), table.c.id.in_(ids))).all())
            return [dict(rows[sid], last_active=activity[sid]) for sid in ids]

    def find_latest_gateway_session_for_peer(self, *, source, user_id=None, session_key=None, chat_id=None, chat_type=None, thread_id=None):
        with self._context.read() as conn:
            if not session_key:
                return None
            return gateway_peers_repo.peer_candidate(conn, self._context.scope, source=source, session_key=session_key, owner=self._context.own_profile, user_id=user_id, chat_id=chat_id, chat_type=chat_type, thread_id=thread_id)

    def list_never_active_keyed_sessions(self, *, older_than_days):
        with self._context.read() as conn:
            return gateway_peers_repo.never_active(conn, self._context.scope, older_than_days)

    def find_orphaned_gateway_sessions(self, *, max_gap_s=None):
        gap = self._ORPHAN_ADOPTION_MAX_GAP_S if max_gap_s is None else float(max_gap_s)
        with self._context.read() as conn:
            return gateway_peers_repo.orphans(conn, self._context.scope, owner=self._context.own_profile, max_gap_s=gap)

    def adopt_orphaned_gateway_session(self, orphan_id, donor_id):
        with self._context.write() as conn:
            return operations.adopt(conn, self._context.scope, orphan_id, donor_id, owner=self._context.own_profile)

    def message_storage_state(self, message_id):
        with self._context.read() as conn:
            row = conn.execute(select(messages.c.session_id, messages.c.active, messages.c.compacted).where(messages.c.store_id == self._context.scope.require_store_id(), messages.c.id == message_id)).mappings().first()
            return dict(row) if row else None

    @property
    def profile_home(self):
        return self._context.scope.profile_home

    def storage_health(self):
        with self._context.read() as conn:
            conn.execute(select(health_sessions.c.id).where(health_sessions.c.store_id == self._context.scope.require_store_id()).limit(1)).first()
        return {'backend': 'postgresql', 'status': 'ok'}

    def referenced_spillover_names(self):
        with self._context.read() as conn:
            return referenced_names(conn, self._context.scope)

    def latest_message_preview(self, session_id):
        with self._context.read() as conn:
            preview = conn.scalar(select(messages.c.roster_preview).where(messages.c.store_id == self._context.scope.require_store_id(), messages.c.session_id == session_id, messages.c.active == 1, messages.c.roster_preview.is_not(None)).order_by(messages.c.id.desc()).limit(1))
        return bytes(preview).decode('utf-8') if preview is not None else ''
