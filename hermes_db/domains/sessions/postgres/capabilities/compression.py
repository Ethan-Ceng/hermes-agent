"""Compression business entry points; operations own short transactions."""

from hermes_db.domains.sessions.postgres.operations import compression


class SessionCompression:
    def publish_compression_child(self, *, parent_session_id, child_session_id, source, messages,
        model=None, model_config=None, system_prompt=None, cwd=None, profile_name=None,
        compression_lock_holder=None, require_compression_lease=True, require_lease_refresh=False,
        lease_ttl_seconds=300.0, watermark=None, watermark_ceiling=None):
        from hermes_db.domains.sessions.postgres.operations.compression_publish import publish
        self._assert_open()
        publish(self._transactions, self.scope, parent_session_id=parent_session_id, child_session_id=child_session_id,
            source=source, messages=messages, model=model, model_config=model_config, system_prompt=system_prompt,
            cwd=cwd, profile_name=profile_name, own_profile=self._own_profile,
            compression_lock_holder=compression_lock_holder, require_compression_lease=require_compression_lease,
            require_lease_refresh=require_lease_refresh, lease_ttl_seconds=lease_ttl_seconds,
            watermark=watermark, watermark_ceiling=watermark_ceiling)

    def get_compression_chain(self, session_id):
        from hermes_db.domains.sessions.postgres.queries import sessions
        from hermes_db.core.values import preferred_children
        with self._read() as conn:
            children = preferred_children(sessions.lineage_rows(conn, self.scope, session_id))
        chain = [session_id] if session_id else []
        while chain and chain[-1] in children:
            child = children[chain[-1]]
            if child in chain:
                raise RuntimeError("Compression lineage contains a cycle")
            chain.append(child)
        return chain

    def get_compression_tip(self, session_id):
        chain = self.get_compression_chain(session_id)
        return chain[-1] if chain else session_id

    def archive_and_compact(self, session_id, compacted_messages, model_config_patch=None, watermark=None,
        lock_holder=None, tail_count=0, carried_messages=None, covered_ids=None, unresolved_held=None, held_for_cas=None):
        self._assert_open()
        return compression.compact(self._transactions, self.scope, session_id, compacted_messages,
            model_config_patch=model_config_patch, watermark=watermark, lock_holder=lock_holder,
            tail_count=tail_count, carried_messages=carried_messages, covered_ids=covered_ids,
            unresolved_held=unresolved_held, held_for_cas=held_for_cas)

    def rewritten_held_row_ids(self, session_id, held):
        from hermes_db.domains.sessions.postgres.support.compression_coverage import Coverage
        from hermes_db.domains.sessions.postgres.queries import messages
        from hermes_db.tables.conversations import messages as table
        with self._read() as conn:
            rows = messages.select_rows(conn, self.scope, [session_id], table.c.active == 1)
            return Coverage(rows).mismatches(held)

    def held_row_mismatches(self, conn, session_id, held):
        from hermes_db.domains.sessions.postgres.support.compression_coverage import Coverage
        from hermes_db.domains.sessions.postgres.queries import messages
        from hermes_db.tables.conversations import messages as table
        return Coverage(messages.select_rows(conn, self.scope, [session_id], table.c.active == 1)).mismatches(held)
