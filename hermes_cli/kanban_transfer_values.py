"""Structured artifact references travel with their relocated attachment bytes."""

import json


def reanchor_artifacts(raw, mapping):
    if raw is None or not mapping:
        return raw
    try:
        value = json.loads(raw)
    except (ValueError, TypeError):
        return raw
    if not isinstance(value, dict) or not isinstance(value.get("artifacts"), list):
        return raw
    relocated = [mapping.get(item, item) if isinstance(item, str) else item for item in value["artifacts"]]
    if relocated == value["artifacts"]:
        return raw
    value["artifacts"] = relocated
    return json.dumps(value, ensure_ascii=False)


def reanchor_tables(tables, mapping):
    for table, field in (("task_runs", "metadata"), ("task_events", "payload")):
        for row in tables[table]:
            row[field] = reanchor_artifacts(row[field], mapping)


def reanchor_sqlite(conn, mapping):
    for table, field in (("task_runs", "metadata"), ("task_events", "payload")):
        for row in conn.execute(f"SELECT id, {field} FROM {table}").fetchall():
            relocated = reanchor_artifacts(row[field], mapping)
            if relocated != row[field]:
                conn.execute(f"UPDATE {table} SET {field} = ? WHERE id = ?", (relocated, row["id"]))
