"""Transcript write entry points; operations own the whole transaction."""

from hermes_db.domains.sessions.postgres.operations import messages as operations


class SessionMessages:
    def append_message(self, session_id, role, content=None, tool_name=None, tool_calls=None, tool_call_id=None,
                       token_count=None, finish_reason=None, reasoning=None, reasoning_content=None, reasoning_details=None,
                       codex_reasoning_items=None, codex_message_items=None, platform_message_id=None, observed=False,
                       effect_disposition=None, _compressed_summary=False, timestamp=None, api_content=None,
                       display_kind=None, display_metadata=None, compression_lock_holder=None, turn_lease_holder=None,
                       turn_lease_ttl_seconds=300.0, message_uid=None):
        self._assert_open()
        msg = dict(locals())
        msg.pop("self")
        return operations.append(self._transactions, self.scope, session_id, [msg], single=True,
            compression_lock_holder=compression_lock_holder, turn_lease_holder=turn_lease_holder,
            turn_lease_ttl_seconds=turn_lease_ttl_seconds)

    def append_messages_batch(self, session_id, messages, compression_lock_holder=None, turn_lease_holder=None,
                              chunk_rows=None, turn_lease_ttl_seconds=300.0):
        self._assert_open()
        if not messages:
            return 0
        if chunk_rows is not None:
            if chunk_rows <= 0:
                raise ValueError("chunk_rows must be positive")
            from hermes_db.domains.sessions.postgres.support.message_codec import codec
            from hermes_state_messages import _parse_tool_calls
            index = {}
            for msg in messages:
                codec._stamp_tool_call_uids(msg, _parse_tool_calls(msg.get("tool_calls")), index)
            if len(messages) > chunk_rows:
                return sum(self.append_messages_batch(session_id, messages[start:start + chunk_rows],
                    compression_lock_holder=compression_lock_holder, turn_lease_holder=turn_lease_holder,
                    turn_lease_ttl_seconds=turn_lease_ttl_seconds) for start in range(0, len(messages), chunk_rows))
        return operations.append(self._transactions, self.scope, session_id, messages,
            compression_lock_holder=compression_lock_holder, turn_lease_holder=turn_lease_holder,
            turn_lease_ttl_seconds=turn_lease_ttl_seconds)

    def replace_messages(self, session_id, messages, active_only=False, archive_dropped=False, reject_active_turn_lease=False):
        self._assert_open()
        operations.replace(self._transactions, self.scope, session_id, messages, active_only=active_only,
                           archive_dropped=archive_dropped, reject_active_turn_lease=reject_active_turn_lease)

    def replace_messages_in_transaction(self, conn, session_id, messages, *, active_only=False, archive_dropped=False,
                                        reject_active_turn_lease=False, expected_active_ids=None):
        self._assert_open()
        operations.replace_on_connection(conn, self.scope, session_id, messages, active_only=active_only,
            archive_dropped=archive_dropped, reject_active_turn_lease=reject_active_turn_lease,
            expected_active_ids=expected_active_ids)

    def rewind_to_message(self, session_id, target_message_id, *, preserve_compaction_handoff=False,
                          expected_active_ids=None, expected_target_content=None):
        with self._write() as conn:
            return operations.rewind(conn, self.scope, session_id, target_message_id,
                preserve_compaction_handoff=preserve_compaction_handoff,
                expected_active_ids=expected_active_ids, expected_target_content=expected_target_content)
