"""Atomic public session creation, selected by the configured owner backend."""

import json
import time


def create_row(db, session_id, source, model, config, prompt, title):
    from hermes_db.health import is_postgresql_store
    if is_postgresql_store(db):
        from hermes_db.integration.runtime_access import runtime_for_store
        return runtime_for_store(db).create_api_session(session_id=session_id, source=source,
            model=model, model_config=config, system_prompt=prompt, title=title)

    def sqlite(conn):
        from hermes_state_mutation_retirement import create_conflict
        if conflict := create_conflict(conn, session_id):
            return None, conflict
        conn.execute("""INSERT INTO sessions(id,source,model,model_config,system_prompt,started_at)
            VALUES(?,?,?,?,?,?)""", (session_id, source, model, json.dumps(config) if config else None, prompt, time.time()))
        if title is not None:
            clean = db.sanitize_title(str(title))
            if clean:
                try:
                    db._resolve_title_conflict(conn, session_id, clean)
                except ValueError as exc:
                    conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
                    return None, f"title:{exc}"
            conn.execute("UPDATE sessions SET title=? WHERE id=?", (clean, session_id))
        return dict(conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()), None

    return db._execute_write(sqlite)
