"""Metadata, visibility and model-route methods; all mutations are scoped."""

import time

from sqlalchemy import select

from hermes_db.operations import sessions as operations
from hermes_db.repositories import sessions as repo
from hermes_db.tables.conversations import sessions
from hermes_db.core.values import encode_config, encode_text, model_config


class SessionMetadata:
    def backfill_repo_roots(self, cwd_to_root):
        pairs = [(cwd, root) for cwd, root in cwd_to_root.items() if cwd and root]
        if not pairs:
            return
        with self._write() as conn:
            repo.lock_store(conn, self.scope, exclusive=True)
            for cwd, root in pairs:
                conn.execute(sessions.update().where(sessions.c.store_id == self.scope.require_store_id(),
                    sessions.c.cwd == cwd, (sessions.c.git_repo_root.is_(None) | (sessions.c.git_repo_root == '')))
                    .values(git_repo_root=root))

    def update_system_prompt(self, session_id, system_prompt):
        self._assert_open()
        operations.set_prompt(self._transactions, self.scope, session_id, system_prompt)

    def update_session_tool_names(self, session_id, pin):
        self._assert_open()
        operations.set_prompt(self._transactions, self.scope, session_id, pin, tools=True)

    def patch_session_model_config(self, session_id, patch):
        if session_id and patch:
            with self._write() as conn:
                operations.patch_model(conn, self.scope, session_id, patch)

    def get_session_model_config_value(self, session_id, key, default=None):
        return model_config((self.get_session(session_id) or {}).get("model_config")).get(key, default)

    def update_session_model(self, session_id, model, provider=None, *, base_url=None, api_mode=None):
        self.flush_token_counts()
        patch = {"browser_model_lock": None}
        if model:
            patch["model"] = model
        if provider:
            route = {"provider": provider, "base_url": base_url or None, "api_mode": api_mode or None}
            patch.update(route, gateway_runtime=route)
        with self._write() as conn:
            operations.patch_model(conn, self.scope, session_id, patch, extra={"model": model})

    def update_session_meta(self, session_id, model_config_json, model=None):
        self.flush_token_counts()
        with self._write() as conn:
            row = repo.lock_session(conn, self.scope, session_id)
            if row:
                repo.update_session(conn, self.scope, session_id, {"model_config": model_config_json, "model": model or row["model"]})

    def update_session_runtime_lock(self, session_id, *, model=None, provider=None, model_options=None,
                                    route_source=None, confirmed=False):
        lock = {"provider": provider or "", "model": model or "", "model_options": model_options or {},
                "route_source": route_source or "", "confirmed": bool(confirmed), "updated_at": time.time()}
        with self._write() as conn:
            row = repo.lock_session(conn, self.scope, session_id)
            if row:
                operations.patch_model(conn, self.scope, session_id, {"browser_model_lock": lock},
                                       extra={"model": model if model is not None else row["model"]})

    def update_conversation_model_config_value(self, session_id, key, update):
        with self._write() as conn:
            if repo.lock_session(conn, self.scope, session_id) is None:
                return None
            tip = repo.compression_tip(conn, self.scope, session_id)
            row = repo.raw_session(conn, self.scope, tip)
            config = model_config(row["model_config"])
            operations.patch_model(conn, self.scope, tip, {key: update(config.get(key))})
            return tip

    def session_ids_with_model_config_key(self, key):
        from hermes_db.backends.postgresql.expressions.json_paths import path_value
        found, cursor = [], None
        with self._read() as conn:
            statement = select(sessions.c.id, sessions.c.started_at, sessions.c.model_config).where(
                sessions.c.store_id == self.scope.require_store_id()).order_by(sessions.c.id).limit(128)
            while True:
                page = statement.where(sessions.c.id > cursor) if cursor is not None else statement
                rows = conn.execute(page).mappings().all()
                if not rows:
                    break
                found.extend((row['started_at'], row['id']) for row in rows
                    if path_value(model_config(row['model_config']), key) is not None)
                cursor = rows[-1]['id']
        return [session_id for _, session_id in sorted(found, key=lambda item: item[0], reverse=True)]

    def set_session_yolo(self, session_id, enabled):
        self.patch_session_model_config(session_id, {"yolo_mode": bool(enabled)})

    @staticmethod
    def session_yolo_enabled(session_meta):
        return bool(model_config((session_meta or {}).get("model_config")).get("yolo_mode"))

    def set_expiry_finalized(self, session_id, finalized=True):
        with self._write() as conn:
            repo.lock_session(conn, self.scope, session_id)
            repo.update_session(conn, self.scope, session_id, {"expiry_finalized": int(finalized)})

    def set_session_archived(self, session_id, archived, *, notify=True):
        with self._write() as conn:
            row = repo.lock_session(conn, self.scope, session_id)
            ids = operations.lineage_flag(conn, self.scope, session_id, "archived", int(archived), extra={"auto_archived": 0})
            if archived:
                from hermes_db.operations.titles import retire_bot_chat
                retire_bot_chat(conn, self.scope, ids)
            newly_archived = archived and row and not row["archived"]
        if newly_archived and notify:
            from hermes_db.integration.events import emit_deleted
            emit_deleted(self._profile, ids, reason="archive", primary=session_id)
        return bool(ids)

    def set_session_hidden(self, session_id, hidden):
        with self._write() as conn:
            return bool(operations.lineage_flag(conn, self.scope, session_id, "hidden", int(hidden)))

    def set_session_pinned(self, session_id, pinned):
        with self._write() as conn:
            row = repo.lock_session(conn, self.scope, session_id)
            ids = operations.lineage_flag(conn, self.scope, session_id, "pinned", int(pinned))
            canonical = row and row["hidden"] and row["title"] == encode_text(self.CANONICAL_BOT_CHAT_TITLE)
            if pinned and not canonical:
                operations.lineage_flag(conn, self.scope, session_id, "hidden", 0)
            return bool(ids)

    def set_session_read(self, session_id, read=True):
        with self._write() as conn:
            return bool(operations.lineage_flag(conn, self.scope, session_id, "last_read_at", time.time() if read else 0.0))

    @staticmethod
    def session_unread(session_row):
        if session_row.get("last_read_at") is None:
            return False
        active = session_row.get("last_active") or session_row.get("started_at")
        return float(active or 0) > float(session_row["last_read_at"])

    def update_session_cwd(self, session_id, cwd, git_branch=None, git_repo_root=None, replace_git_meta=False):
        if not session_id or not cwd:
            return None
        with self._write() as conn:
            row = repo.lock_session(conn, self.scope, session_id)
            if row is None:
                return None
            generation = int(row["git_metadata_generation"] or 0) + 1
            values = {"cwd": cwd, "git_metadata_generation": generation}
            for name, value in (("git_branch", git_branch), ("git_repo_root", git_repo_root)):
                value = (value or "").strip()
                if value or replace_git_meta or row["cwd"] != cwd:
                    values[name] = value or None
            repo.update_session(conn, self.scope, session_id, values)
            return generation

    def publish_session_git_metadata(self, session_id, cwd, generation, git_branch=None, git_repo_root=None):
        if not session_id or not cwd or type(generation) is not int or generation < 1:
            return False
        values = {name: value.strip() for name, value in (("git_branch", git_branch), ("git_repo_root", git_repo_root)) if value and value.strip()}
        if not values:
            return False
        with self._write() as conn:
            repo.lock_session(conn, self.scope, session_id)
            return repo.update_session(conn, self.scope, session_id, values,
                sessions.c.cwd == cwd, sessions.c.git_metadata_generation == generation) == 1

    def touch_session_activity(self, session_id, ts=None, *, description=None, provenance=None):
        from agent.session_activity import bound_activity_description, normalize_activity_provenance
        if not session_id:
            return
        when = float(time.time() if ts is None else ts)
        with self._write() as conn:
            repo.lock_session(conn, self.scope, session_id)
            repo.update_session(conn, self.scope, session_id, {"last_activity_at": when,
                "last_activity_description": encode_text(bound_activity_description(description)),
                "last_activity_provenance": normalize_activity_provenance(provenance).value},
                (sessions.c.last_activity_at.is_(None)) | (sessions.c.last_activity_at < when))

    def clear_session_activity_labels(self, session_id):
        if not session_id:
            return
        with self._write() as conn:
            repo.lock_session(conn, self.scope, session_id)
            repo.update_session(conn, self.scope, session_id, {"last_activity_description": b"", "last_activity_provenance": "unknown"})

    def retire_undrained_queue_rows(self, session_id):
        with self._write() as conn:
            if repo.lock_session(conn, self.scope, session_id) is None:
                return 0
            return operations.retire_queued_on_connection(conn, self.scope, session_id)

    def promote_to_session_reset(self, session_id, reason="session_reset"):
        from hermes_state_common import _RECOVERABLE_END_REASONS

        if not session_id:
            return False
        with self._write() as conn:
            row = repo.lock_session(conn, self.scope, session_id)
            if row is None or (row["ended_at"] is not None and row["end_reason"] not in _RECOVERABLE_END_REASONS):
                return False
            repo.update_session(conn, self.scope, session_id, {"ended_at": time.time(), "end_reason": reason})
            repo.bump_generation(conn, self.scope, row, reason)
            return True

    def unarchive_recoverable_session(self, session_id):
        from hermes_state_common import _RECOVERABLE_END_REASONS

        if not session_id:
            return False
        with self._write() as conn:
            row = repo.lock_session(conn, self.scope, session_id)
            if row is None or not row["archived"]:
                return False
            tip_id = repo.compression_tip(conn, self.scope, session_id)
            tip = repo.raw_session(conn, self.scope, tip_id)
            if tip["end_reason"] not in _RECOVERABLE_END_REASONS:
                return False
            operations.lineage_flag(conn, self.scope, session_id, "archived", 0, extra={"auto_archived": 0})
            repo.update_session(conn, self.scope, tip_id, {"ended_at": None, "end_reason": None})
            return True

    def declared_scope_identity(self, session_id):
        row = self.get_session(session_id)
        if row is None:
            return False, ""
        config = model_config(row["model_config"])
        markers = [config.get(name) for name in ("_branched_from", "_delegate_from")]
        parent = row["parent_session_id"]
        fork = row["source"] == "tool" or (parent in markers if parent else any(value is not None for value in markers))
        return fork, str(row["source"] or "").strip()
