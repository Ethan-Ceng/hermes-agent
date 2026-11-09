"""Bounded session-list selection and detached page hydration."""

from sqlalchemy import and_, case, exists, func, or_, select

from hermes_db.repositories import sessions as repo
from hermes_db.tables.conversations import messages, sessions
from hermes_db.tables.runtime import session_admissions
from hermes_db.core.values import decode_text, preferred_children


def filters(conn, scope, *, source=None, sources=None, session_key=None, exclude_sources=None, cwd_prefix=None,
            min_message_count=0, archived_only=False, include_archived=False, exclude_children=False,
            include_subagents=False, local_created_sources=None, include_hidden=True, workspace_key=None):
    clauses = [sessions.c.store_id == scope.require_store_id()]
    labels = [source] if source else list(sources or [])
    if labels:
        source_filter = sessions.c.source.in_(labels)
        if local_created_sources and "local" in labels:
            source_filter = or_(sessions.c.source.in_([value for value in labels if value != "local"]),
                and_(sessions.c.source == "local", sessions.c.created_source.in_(local_created_sources)))
        clauses.append(source_filter)
    if session_key:
        clauses.append(sessions.c.session_key == session_key)
    if exclude_sources:
        clauses.append(sessions.c.source.not_in(exclude_sources))
    if cwd_prefix:
        prefix = cwd_prefix.rstrip("/\\") or cwd_prefix
        clauses.append(or_(sessions.c.cwd == prefix, sessions.c.cwd.startswith(prefix + "/", autoescape=True),
                            sessions.c.cwd.startswith(prefix + "\\", autoescape=True)))
    if workspace_key:
        clauses.append(workspace_clause(workspace_key))
    if min_message_count > 0:
        clauses.append(sessions.c.message_count >= min_message_count)
    if archived_only:
        clauses.append(sessions.c.archived == 1)
    elif not include_archived:
        clauses.append(sessions.c.archived == 0)
    if not include_hidden and not archived_only:
        clauses.append(sessions.c.hidden == 0)
    if exclude_children:
        clauses.append(sessions.c.lineage_root_id == sessions.c.id)
        if not include_subagents:
            clauses.append(sessions.c.has_delegate_marker == 0)
    return clauses


def workspace_clause(key):
    prefix = key.rstrip('/\\') or key
    return or_(sessions.c.git_repo_root == prefix, and_(func.coalesce(sessions.c.git_repo_root, '') == '',
        or_(sessions.c.cwd == prefix, sessions.c.cwd.startswith(prefix + '/', autoescape=True),
            sessions.c.cwd.startswith(prefix + '\\', autoescape=True))))


def last_activity(conn, table=sessions):
    from hermes_cli.timefmt import EPOCH_MIN, EPOCH_MAX

    latest_message = select(func.max(messages.c.timestamp)).where(messages.c.store_id == table.c.store_id,
        messages.c.session_id == table.c.id, messages.c.timestamp.between(EPOCH_MIN, EPOCH_MAX)).correlate(table).scalar_subquery()
    activity = case((table.c.last_activity_at.between(EPOCH_MIN, EPOCH_MAX), table.c.last_activity_at), else_=None)
    maximum = func.max if conn.dialect.name == "sqlite" else func.greatest
    newest = maximum(func.coalesce(latest_message, EPOCH_MIN - 1), func.coalesce(activity, EPOCH_MIN - 1))
    fallback = case((table.c.started_at.between(EPOCH_MIN, EPOCH_MAX), table.c.started_at), else_=None)
    return case((newest >= EPOCH_MIN, newest), else_=fallback)


def lineage_activity(conn):
    peer = sessions.alias("activity_peer")
    return select(func.max(last_activity(conn, peer))).where(peer.c.store_id == sessions.c.store_id,
        peer.c.lineage_root_id == sessions.c.lineage_root_id).correlate(sessions).scalar_subquery()


def search_filters(conn, id_query, search_query):
    clauses = []
    peer = sessions.alias("search_peer")
    common = (peer.c.store_id == sessions.c.store_id, peer.c.lineage_root_id == sessions.c.lineage_root_id)
    if id_query:
        clauses.append(exists(select(1).where(*common, func.lower(peer.c.id).contains(id_query.strip().lower(), autoescape=True))))
    if search_query:
        needle = search_query.strip().lower()
        compact = needle
        title = func.lower(func.coalesce(peer.c.title_search, ""))
        normalized = title
        for character in ("-", "_", ".", " "):
            normalized = func.replace(normalized, character, "")
            compact = compact.replace(character, "")
        terms = [title.contains(needle, autoescape=True), func.lower(peer.c.id).contains(needle, autoescape=True)]
        if compact:
            terms.append(normalized.contains(compact, autoescape=True))
        clauses.append(exists(select(1).where(*common, or_(*terms))))
    return clauses


def launch_stub_filter(scope):
    return or_(sessions.c.message_count > 0, exists(select(1).where(
        session_admissions.c.store_id == scope.require_store_id(), session_admissions.c.target_session_id == sessions.c.id)))


def bounded_roots(conn, scope, exclude_sources, candidate_limit, lineage_limit):
    candidates = list(conn.execute(select(sessions.c.lineage_root_id).where(*filters(conn, scope,
        exclude_sources=exclude_sources, include_hidden=False))
        .order_by(last_activity(conn).desc(), sessions.c.id.desc()).limit(candidate_limit)).scalars())
    roots = list(dict.fromkeys(candidates))
    sizes = dict(conn.execute(select(sessions.c.lineage_root_id, func.count()).where(
        sessions.c.store_id == scope.require_store_id(), sessions.c.lineage_root_id.in_(roots))
        .group_by(sessions.c.lineage_root_id)).all())
    selected, total = [], 0
    for root_id in roots:
        count = sizes.get(root_id, 0)
        if count and total + count < lineage_limit:
            selected.append(root_id)
            total += count
    return selected


def hydrate(conn, scope, ids, *, compact=False):
    if not ids:
        return []
    rows = list(conn.execute(select(sessions, last_activity(conn).label("last_active")).where(
        sessions.c.store_id == scope.require_store_id(), sessions.c.id.in_(ids))).mappings())
    full_rows = {} if compact else repo.get_sessions(conn, scope, ids)
    previews = _previews(conn, scope, ids)
    output = []
    for row in rows:
        value = repo.business_row(row) if compact else full_rows[row["id"]]
        value["last_active"] = row["last_active"]
        # This projection is separate from the bounded tool-output search index.
        value["preview"] = previews.get(row["id"], "")
        if compact:
            for field in ("system_prompt", "system_prompt_hash", "git_metadata_generation"):
                value.pop(field, None)
        output.append(value)
    by_id = {row["id"]: row for row in output}
    return [by_id[session_id] for session_id in ids if session_id in by_id]


def _previews(conn, scope, session_ids):
    from hermes_state_common import _shape_preview

    ranked = select(messages.c.session_id, messages.c.preview_text, func.row_number().over(
        partition_by=messages.c.session_id, order_by=(messages.c.timestamp, messages.c.id)).label("position"))
    ranked = ranked.where(messages.c.store_id == scope.require_store_id(), messages.c.session_id.in_(session_ids),
                          messages.c.preview_text.is_not(None), messages.c.role == "user").subquery()
    rows = conn.execute(select(ranked.c.session_id, ranked.c.preview_text).where(ranked.c.position == 1))
    return {session_id: _shape_preview(decode_text(value)) for session_id, value in rows}


def project_tips(conn, scope, rows, *, compact=False):
    candidates = [row["id"] for row in rows if row.get("end_reason") == "compression"]
    if not candidates:
        return rows
    lineage = list(conn.execute(select(sessions.c.id, sessions.c.parent_session_id, sessions.c.lineage_root_id,
        sessions.c.started_at, sessions.c.ended_at, sessions.c.end_reason, last_activity(conn).label("_chain_activity")).where(
        sessions.c.store_id == scope.require_store_id(), sessions.c.lineage_root_id.in_(candidates))).mappings())
    chains = _chains_by_root(lineage, candidates)
    hydrated = hydrate(conn, scope, [chain[-1] for chain in chains.values() if len(chain) > 1], compact=compact)
    tips = {row["id"]: row for row in hydrated}
    result = []
    projected_keys = ("id", "ended_at", "end_reason", "message_count", "tool_call_count", "title", "last_active",
                      "preview", "model", "system_prompt", "cwd", "git_branch", "git_repo_root")
    for row in rows:
        if row.get("end_reason") != "compression":
            result.append(row)
            continue
        chain = chains.get(row["id"], [row["id"]])
        tip = tips.get(chain[-1])
        if len(chain) == 1 or tip is None:
            result.append(row)
            continue
        merged = dict(row)
        merged.update({name: tip[name] for name in projected_keys if name in tip})
        if merged.get("title") is None:
            merged["title"] = row.get("title")
        merged.update(_lineage_root_id=row["id"], _lineage_ids=chain, continuation_kind="compression")
        result.append(merged)
    return result


def _chains_by_root(rows, roots):
    children = preferred_children(rows)
    chains = {}
    for root_id in roots:
        chain = [root_id]
        while chain[-1] in children:
            child_id = children[chain[-1]]
            if child_id in chain:
                from hermes_db.errors import StorageWriteError
                raise StorageWriteError("Conversation lineage contains a cycle")
            chain.append(child_id)
        chains[root_id] = chain
    return chains
