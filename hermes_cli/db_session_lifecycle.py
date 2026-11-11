"""Post-commit removal of session snapshots, confined to the configured directory."""

import glob
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def remove_snapshots(sessions_dir, session_ids):
    if sessions_dir is None:
        return
    base = Path(sessions_dir).resolve()
    for session_id in session_ids:
        targets = [base / f"{session_id}{suffix}" for suffix in (".json", ".jsonl")]
        targets.append(base / f"session_{session_id}.json")
        if Path(session_id).name == session_id and "/" not in session_id and "\\" not in session_id:
            try:
                targets.extend(base.glob(f"request_dump_{glob.escape(session_id)}_*.json"))
            except OSError:
                logger.warning("Session dump lookup failed after committed deletion", exc_info=True)
        for target in targets:
            try:
                if target.resolve().is_relative_to(base):
                    target.unlink(missing_ok=True)
            except OSError:
                logger.warning("Session snapshot cleanup failed after committed deletion", exc_info=True)


from hermes_db.domains.sessions.postgres.lifecycle import SessionLifecycle
from hermes_db.domains.sessions.postgres.catalog import SessionCatalog


class OwnedSessionLifecycle(SessionLifecycle):

    def _lease_callback(self, callback, *args):
        if callback is None:
            return None
        try:
            with self._context.profile.activate():
                return callback(*args)
        except Exception:
            logger.debug('Session lease callback failed', exc_info=True)
        return None

    def _after_session_delete(self, targets, *, primary=None, reason='delete', sessions_dir=None):
        self._context.effects.deleted(targets, reason=reason, primary=primary)
        remove_snapshots(sessions_dir, targets)
        self.collect_retired_media()

    def collect_retired_media(self):
        self._context.effects.collect_media(self._context)

    def _export_limit(self, maximum):
        self._context.assert_open()
        if maximum is None:
            maximum = self._context.transcript_limits.export_limit()
        return maximum

    def _emit_archives(self, events):
        for primary, ids in events:
            self._context.effects.deleted(ids, reason='archive', primary=primary)

    def purge_profile_state(self, profile):
        with self._context.write() as conn:
            return self._context.effects.purge_profile(conn, self._context.scope, profile)

    def first_generation(self, derive, *, pinned=None, spent=None):
        with self._context.profile.activate():
            return self.first_generation_data(derive, pinned=pinned, spent=spent)

    def keep_passed_fences(self, derive, session_id):
        with self._context.profile.activate():
            return self.keep_passed_fences_data(derive, session_id)


class OwnedSessionCatalog(SessionCatalog):
    def set_session_archived(self, session_id, archived, *, notify=True):
        found, newly_archived = self.archive_session_data(session_id, archived)
        if newly_archived is not None and notify:
            self._context.effects.deleted(newly_archived, reason='archive', primary=session_id)
        return found


def profile_limit(profile, resolve):
    with profile.activate():
        return resolve()
