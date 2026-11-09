"""Named dashboard and event-tail reads on the selected Board backend."""

from hermes_db.domains.kanban.api import domain_operation


@domain_operation("queries")
def latest_event_id(conn):
    rows = conn.execute("SELECT COALESCE(MAX(id), 0) AS m FROM task_events", ()).fetchall()
    return int(rows[0]["m"]) if rows else 0


@domain_operation("queries")
def events_after(conn, cursor, *, limit=200, with_task=False):
    columns = "e.id, e.task_id, e.run_id, e.kind, e.payload, e.created_at"
    join = ""
    if with_task:
        columns += ", t.assignee, t.tenant"
        join = " LEFT JOIN tasks t ON t.id = e.task_id"
    rows = conn.execute(f"SELECT {columns} FROM task_events e{join} WHERE e.id > ? ORDER BY e.id ASC LIMIT {int(limit)}", (cursor,)).fetchall()
    return [dict(row) for row in rows]


@domain_operation("queries")
def tasks_by_ids(conn, task_ids):
    ids = tuple(dict.fromkeys(task_ids))
    if not ids:
        return {}
    placeholders = ",".join("?" for _ in ids)
    return {row["id"]: dict(row) for row in conn.execute(f"SELECT * FROM tasks WHERE id IN ({placeholders})", ids)}


def summarize_board(links, comments, child_statuses, tenants):
    link_counts, progress = {}, {}
    for row in links:
        link_counts.setdefault(row["parent_id"], {"parents": 0, "children": 0})["children"] += 1
        link_counts.setdefault(row["child_id"], {"parents": 0, "children": 0})["parents"] += 1
    for row in child_statuses:
        value = progress.setdefault(row["pid"], {"done": 0, "total": 0})
        value["total"] += 1
        value["done"] += row["cstatus"] == "done"
    return link_counts, {row["task_id"]: row["n"] for row in comments}, progress, tenants


@domain_operation("queries")
def board_rollups(conn):
    return summarize_board(conn.execute("SELECT parent_id, child_id FROM task_links").fetchall(),
        conn.execute("SELECT task_id, COUNT(*) AS n FROM task_comments GROUP BY task_id").fetchall(),
        conn.execute("SELECT l.parent_id AS pid, t.status AS cstatus FROM task_links l JOIN tasks t ON t.id = l.child_id").fetchall(),
        [row["tenant"] for row in conn.execute("SELECT DISTINCT tenant FROM tasks WHERE tenant IS NOT NULL ORDER BY tenant")])


@domain_operation("queries")
def board_status_counts(conn):
    return {row["status"]: int(row["n"]) for row in conn.execute("SELECT status, COUNT(*) AS n FROM tasks GROUP BY status")}


@domain_operation("queries")
def active_worker_rows(conn):
    return [dict(row) for row in conn.execute(
        "SELECT r.id AS run_id, r.task_id, t.title AS task_title, t.status AS task_status, "
        "t.assignee AS task_assignee, r.profile, r.worker_pid, r.started_at, r.claim_lock, "
        "r.claim_expires, r.last_heartbeat_at, r.max_runtime_seconds "
        "FROM task_runs r JOIN tasks t ON t.id = r.task_id "
        "WHERE r.ended_at IS NULL AND r.worker_pid IS NOT NULL AND t.status = 'running' ORDER BY r.started_at ASC").fetchall()]
