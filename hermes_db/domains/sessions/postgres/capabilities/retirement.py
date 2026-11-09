"""Deletion/export entry points; transactional retirement lives in operations."""

from hermes_db.domains.sessions.postgres.queries import retirement


class SessionRetirement:
    def delete_session(self, session_id, sessions_dir=None, expected_delete_ids=None, expected_display_messages=None,
        exclude_active_write_guards=False, include_compression_chain=False):
        from hermes_db.domains.sessions.postgres.operations import retirement as operations

        if include_compression_chain:
            return self.delete_sessions([session_id], sessions_dir=sessions_dir,
                exclude_active_write_guards=exclude_active_write_guards, include_compression_chain=True) > 0
        with self._write() as conn:
            deleted, targets = operations.delete_one(conn, self.scope, session_id, expected_delete_ids=expected_delete_ids,
                expected_display_messages=expected_display_messages, exclude_active_write_guards=exclude_active_write_guards)
        if deleted:
            self._after_session_delete(targets, primary=session_id, sessions_dir=sessions_dir)
        return deleted

    def delete_sessions(self, session_ids, sessions_dir=None, exclude_active_write_guards=False, skipped_ids=None,
                        include_compression_chain=False):
        from hermes_db.domains.sessions.postgres.operations import retirement as operations

        with self._write() as conn:
            count, targets, skipped = operations.delete_many(conn, self.scope, session_ids,
                exclude_active_write_guards=exclude_active_write_guards, include_compression_chain=include_compression_chain)
        if skipped_ids is not None:
            skipped_ids.extend(skipped)
        if count:
            self._after_session_delete(targets, primary=session_ids[0] if len(session_ids) == 1 else None, sessions_dir=sessions_dir)
        return count

    def _after_session_delete(self, targets, *, primary=None, reason="delete", sessions_dir=None):
        from hermes_db.integration.events import emit_deleted
        from hermes_db.domains.sessions.postgres.capabilities.files import remove

        emit_deleted(self._profile, targets, reason=reason, primary=primary)
        remove(sessions_dir, targets)
        self.collect_retired_media()

    def collect_retired_media(self):
        from hermes_db.domains.sessions.postgres.capabilities.media import collect
        collect(self)

    def _export_limit(self, maximum):
        self._assert_open()
        if maximum is None:
            from hermes_state import resolved_max_export_messages
            with self._profile.activate():
                maximum = resolved_max_export_messages()
        return maximum

    def assert_export_safe(self, session_id, max_messages=None):
        from hermes_state import SessionExportTooLargeError
        maximum = self._export_limit(max_messages)
        if maximum < 0:
            raise ValueError("max_messages must be non-negative")
        if maximum == 0:
            return 0
        with self._read() as conn:
            count = retirement.export_count(conn, self.scope, session_id, maximum)
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
        with self._read() as conn:
            return retirement.native_targets(conn, self.scope, session_id)
