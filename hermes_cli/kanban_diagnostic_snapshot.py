"""Named diagnostic input read; raw database access stays behind the backend boundary."""

from hermes_db.domains.kanban.api import domain_operation


@domain_operation("diagnostic_snapshot")
def diagnostic_snapshot(conn, task_id=None, *, task_ids=None):
    from hermes_cli import kanban_db as kb
    condition, params = ("id = ?", (task_id,)) if task_id is not None else ("status != 'archived'", ())
    if task_ids is not None:
        params = tuple(dict.fromkeys(task_ids))
        if not params:
            return []
        condition = "id IN (" + ",".join("?" for _ in params) + ")"
    rows = list(conn.execute(f"SELECT * FROM tasks WHERE {condition}", params))
    ids = [row["id"] for row in rows]
    if not ids:
        return []
    by_table = {}
    placeholders = ",".join("?" for _ in ids)
    for table in ("task_events", "task_runs"):
        by = {task: [] for task in ids}
        for row in conn.execute(f"SELECT * FROM {table} WHERE task_id IN ({placeholders}) ORDER BY id", tuple(ids)):
            by[row["task_id"]].append(row)
        by_table[table] = by
    contexts = kb.task_graph_contexts(conn, ids)
    return [(row, by_table["task_events"][row["id"]], by_table["task_runs"][row["id"]], contexts[row["id"]]) for row in rows]
