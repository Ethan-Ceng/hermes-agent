"""Scoped delete selection and bounded export probes; no commits or file I/O."""

from sqlalchemy import func, or_, select

from hermes_db.repositories import runtime, sessions
from hermes_db.repositories.gateway import marker
from hermes_db.tables.conversations import messages, sessions as table
from hermes_state_local import POLICY_PREFIX


def local_members(conn, scope, session_id):
    row = sessions.raw_session(conn, scope, session_id)
    owner = row["chat_id"] if row and row["chat_id"] else session_id
    receipt = marker(runtime.meta(conn, scope, POLICY_PREFIX + owner))
    if owner != session_id and (receipt is None or session_id not in (receipt.get("lineage") or ())):
        owner = session_id
        receipt = marker(runtime.meta(conn, scope, POLICY_PREFIX + owner))
    lineage = receipt.get("lineage") if receipt else None
    if not isinstance(lineage, list):
        return [session_id]
    return list(dict.fromkeys([session_id, owner, *(sid for sid in lineage if isinstance(sid, str))]))


def delegate_children(conn, scope, parent_ids):
    seeds = {sid for sid in parent_ids if sid}
    found, frontier = set(seeds), list(seeds)
    origin = table.c.delegate_origin
    while frontier:
        next_frontier = []
        for start in range(0, len(frontier), 1000):
            chunk = frontier[start:start + 1000]
            rows = conn.execute(select(table.c.id).where(table.c.store_id == scope.require_store_id(),
                or_(origin.in_([sid.encode('utf-8') for sid in chunk]),
                    table.c.parent_session_id.in_(chunk) & (table.c.has_delegate_marker == 1)))).scalars()
            for sid in rows:
                if sid not in found:
                    found.add(sid)
                    next_frontier.append(sid)
        frontier = next_frontier
    return sorted(found - seeds)


def native_targets(conn, scope, session_id):
    if sessions.raw_session(conn, scope, session_id) is None:
        return []
    members = local_members(conn, scope, session_id)
    return [session_id, *sorted(set(members) - {session_id}), *delegate_children(conn, scope, members)]


def export_count(conn, scope, session_id, maximum):
    bounded = select(messages.c.id).where(messages.c.store_id == scope.require_store_id(),
        messages.c.session_id == session_id).limit(maximum + 1).subquery()
    return conn.scalar(select(func.count()).select_from(bounded))


def expand_native(conn, scope, session_id, *, compression=False):
    members = local_members(conn, scope, session_id)
    if compression:
        members = compression_members(conn, scope, members)
        members = list(dict.fromkeys(member for sid in members for member in local_members(conn, scope, sid)))
    return list(dict.fromkeys([*members, *delegate_children(conn, scope, members)]))


def compression_members(conn, scope, session_ids):
    from hermes_db.core.values import explicit_fork

    roots = select(table.c.lineage_root_id).where(table.c.store_id == scope.require_store_id(), table.c.id.in_(session_ids))
    rows = {row["id"]: dict(row) for row in conn.execute(select(table).where(table.c.store_id == scope.require_store_id(),
        table.c.lineage_root_id.in_(roots))).mappings()}
    edges = {}
    for row in rows.values():
        parent = rows.get(row["parent_session_id"])
        if parent is None or parent["end_reason"] != "compression" or explicit_fork(row):
            continue
        edges.setdefault(row["id"], set()).add(parent["id"])
        edges.setdefault(parent["id"], set()).add(row["id"])
    found, frontier = set(session_ids), list(session_ids)
    while frontier:
        fresh = set().union(*(edges.get(sid, set()) for sid in frontier)) - found
        found.update(fresh)
        frontier = list(fresh)
    return sorted(found)


def display_snapshot(conn, scope, session_id):
    from hermes_db.message_codec import codec
    from hermes_db.session_message_reads import _display_page

    if sessions.raw_session(conn, scope, session_id) is None:
        return None
    missing = conn.scalar(select(messages.c.id).where(messages.c.store_id == scope.require_store_id(),
        messages.c.session_id == session_id, or_(messages.c.display_order.is_(None), messages.c.display_identity.is_(None))).limit(1))
    if missing is not None:
        return None
    return [codec._row_to_message_dict(row, warn_context="verified delete", summary_flag=True)
            for row in _display_page(conn, scope, session_id, None, 0, False)]


def canonical_targets(conn, scope, session_id):
    from hermes_db.repositories.lineage import validate_local_receipt
    from hermes_db.repositories.mutation_binding import same_history_owner

    targets = set(local_members(conn, scope, session_id))
    for sid in list(targets):
        raw = runtime.meta(conn, scope, POLICY_PREFIX + sid)
        if raw is not None:
            import json
            validate_local_receipt(conn, scope, json.loads(raw), sid)
    anchors, frontier = dict.fromkeys(targets, session_id), list(targets)
    while frontier:
        found = {}
        for sid in frontier:
            for candidate in compression_neighbors(conn, scope, sid):
                if candidate not in targets and candidate not in found and same_history_owner(conn, scope, anchors[sid], candidate):
                    found[candidate] = anchors[sid]
        for candidate in delegate_children(conn, scope, frontier):
            if candidate not in targets:
                found.setdefault(candidate, candidate)
        if not found:
            break
        anchors.update(found)
        targets.update(found)
        frontier = list(found)
    return [session_id, *sorted(targets - {session_id})]


def compression_neighbors(conn, scope, session_id):
    from hermes_db.core.values import explicit_fork

    row = sessions.raw_session(conn, scope, session_id)
    if row is None:
        return []
    neighbors = []
    parent = sessions.raw_session(conn, scope, row["parent_session_id"]) if row["parent_session_id"] else None
    if parent and parent["end_reason"] == "compression" and not explicit_fork(row):
        neighbors.append(parent["id"])
    if row["end_reason"] == "compression":
        children = conn.execute(select(table).where(table.c.store_id == scope.require_store_id(),
            table.c.parent_session_id == session_id)).mappings()
        neighbors.extend(child["id"] for child in children if not explicit_fork(child))
    return neighbors
