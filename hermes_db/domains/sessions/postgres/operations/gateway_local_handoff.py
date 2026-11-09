"""Messaging peer takeover of a current Local target settles its whole receipt."""

from sqlalchemy import select

from hermes_db.domains.sessions.postgres.operations.titles import RANK
from hermes_db.domains.sessions.postgres.queries import sessions
from hermes_db.domains.sessions.postgres.queries.gateway import marker
from hermes_db.tables.conversations import sessions as table
from hermes_db.tables.runtime import state_meta
from hermes_db.domains.runtime.receipts import POLICY_PREFIX

LANE_FIELDS = ("session_key", "source", "user_id", "chat_id", "chat_type", "thread_id", "display_name", "origin_json", "transport_profile")


def hand_off_moved(conn, scope, target_ids, *, messaging_platform):

    rows = conn.execute(select(state_meta.c.key, state_meta.c.value).where(state_meta.c.store_id == scope.require_store_id(),
        state_meta.c.key.startswith(POLICY_PREFIX, autoescape=True))).all()
    for key, raw in rows:
        receipt = marker(raw)
        entry = receipt.get("entry") if receipt else None
        target = entry.get("session_id") if isinstance(entry, dict) else None
        if target not in target_ids:
            continue
        row = sessions.raw_session(conn, scope, target)
        if row is None or row["session_key"] is None or row["session_key"] == receipt.get("route") or messaging_platform(row["source"]) is None:
            continue
        owner = key[len(POLICY_PREFIX):]
        lineage = receipt.get("lineage", [owner])
        if not isinstance(lineage, list) or not all(isinstance(sid, str) for sid in lineage):
            continue
        segments = list(dict.fromkeys([owner, *lineage]))
        _settle(conn, scope, owner, row, segments)
        conn.execute(state_meta.delete().where(state_meta.c.store_id == scope.require_store_id(), state_meta.c.key == key))


def _settle(conn, scope, owner, target, segments):
    rows = [sessions.raw_session(conn, scope, sid) for sid in segments]
    for root in sorted({row["lineage_root_id"] for row in rows if row}):
        sessions.lock_root(conn, scope, root)
    conn.execute(table.update().where(table.c.store_id == scope.require_store_id(), table.c.id.in_(segments), table.c.id != target["id"])
        .values(**{name: target[name] for name in LANE_FIELDS}))
    head = target["id"]
    if head in segments:
        index = segments.index(head)
        while index > 0:
            parent = sessions.raw_session(conn, scope, segments[index - 1])
            if parent is None or parent["end_reason"] != "compression":
                break
            index -= 1
        head = segments[index]
    _move_title(conn, scope, owner, head)


def _move_title(conn, scope, owner, head):
    old, current = (sessions.raw_session(conn, scope, sid) for sid in (owner, head))
    if owner == head or old is None or old["title"] is None or current is None:
        return
    if current["title"] and _rank(current["title_source"]) >= _rank(old["title_source"]):
        return
    for sid in (owner, head):
        sessions.update_session(conn, scope, sid, {"title": None, "title_search": None})
    sessions.update_session(conn, scope, head, {"title": old["title"], "title_search": old["title_search"],
        "title_source": old["title_source"], "hidden": old["hidden"]})


def _rank(source):
    return RANK.get(source, 2 if source is None else 0)
