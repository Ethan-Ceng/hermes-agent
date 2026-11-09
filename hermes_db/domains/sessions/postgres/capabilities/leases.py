"""Lease entry points and bounded waiting outside database transactions."""

import logging
import time

from hermes_db.errors import StorageBusyError
from hermes_db.domains.sessions.postgres.operations import leases

logger = logging.getLogger(__name__)


class SessionLeases:
    def _change_lease(self, session_id, holder, action, *, turn=False, ttl_seconds=300, patience_s=None):
        self._assert_open()
        if not session_id or not holder:
            return False if action != "release" else None
        now = time.time()
        with self._transactions.write(lock_timeout=patience_s) as conn:
            return leases.change(conn, self.scope, session_id, holder, action,
                turn=turn, ttl_seconds=ttl_seconds, now=now)

    def try_acquire_compression_lock(self, session_id, holder, ttl_seconds=300.0):
        return self._change_lease(session_id, holder, "acquire", ttl_seconds=ttl_seconds)

    def refresh_compression_lock(self, session_id, holder, ttl_seconds=300.0):
        return self._change_lease(session_id, holder, "renew", ttl_seconds=ttl_seconds)

    def release_compression_lock(self, session_id, holder):
        self._change_lease(session_id, holder, "release")

    def get_compression_lock_holder(self, session_id):
        with self._read() as conn:
            return leases.compression_holder(conn, self.scope, session_id) if session_id else None

    def try_acquire_session_turn_lease(self, session_id, holder, *, ttl_seconds=300.0, patience_s=None):
        return self._change_lease(session_id, holder, "acquire", turn=True,
                                  ttl_seconds=ttl_seconds, patience_s=patience_s)

    def refresh_session_turn_lease(self, session_id, holder, *, ttl_seconds=300.0, patience_s=None):
        return self._change_lease(session_id, holder, "renew", turn=True,
                                  ttl_seconds=ttl_seconds, patience_s=patience_s)

    def release_session_turn_lease(self, session_id, holder):
        self._change_lease(session_id, holder, "release", turn=True)

    def session_turn_lease_expires_at(self, session_id, holder):
        with self._read() as conn:
            return leases.expiry(conn, self.scope, session_id, holder) if session_id and holder else None

    def _session_turn_lease_key(self, session_id):
        from hermes_db.domains.sessions.postgres.queries import sessions
        with self._read() as conn:
            row = sessions.raw_session(conn, self.scope, session_id)
            return row["lineage_root_id"] if row else session_id

    def _lease_callback(self, callback, *args):
        if callback is None:
            return None
        try:
            with self._profile.activate():
                return callback(*args)
        except Exception:
            logger.debug("Session lease callback failed", exc_info=True)
        return None

    def acquire_session_turn_lease(self, session_id, holder, *, ttl_seconds=300.0,
        wait_seconds=1800.0, poll_interval_seconds=1.0, on_wait=None,
        wait_notice_interval_seconds=15.0, should_abort=None, acquire_patience_s=0.5, on_contended=None):
        deadline = time.monotonic() + max(0.0, float(wait_seconds))
        patience, started, last_notice = acquire_patience_s, None, None
        while True:
            self._assert_open()
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
