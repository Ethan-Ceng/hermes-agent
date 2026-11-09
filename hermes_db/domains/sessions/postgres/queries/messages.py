"""Scoped transcript rows and atomic projection maintenance on a held connection."""

from sqlalchemy import and_, case, func, insert, or_, select

from hermes_db.domains.sessions.postgres.support.message_codec import codec, decoded_row, stored_values
from hermes_db.domains.sessions.postgres.support.message_preview import preview_text, roster_preview
from hermes_db.domains.sessions.postgres.support.search_projection import content_text, projection
from hermes_db.domains.sessions.postgres.support.archive_projection import spillover_names
from hermes_db.backends.postgresql.expressions.projections import display_projection
from hermes_db.domains.sessions.postgres.queries import sessions as session_repo
from hermes_db.tables.conversations import messages, sessions


def where(scope, session_ids=None):
    clauses = [messages.c.store_id == scope.require_store_id()]
    if session_ids is not None:
        clauses.append(messages.c.session_id.in_(session_ids))
    return and_(*clauses)


def select_rows(conn, scope, session_ids, *conditions, limit=None, offset=0, latest=False):
    statement = select(messages).where(where(scope, session_ids), *conditions).order_by(
        messages.c.id.desc() if latest else messages.c.id)
    if limit is not None:
        statement = statement.limit(limit)
    if offset:
        statement = statement.offset(offset)
    rows = [decoded_row(row) for row in conn.execute(statement).mappings()]
    return rows[::-1] if latest else rows


def one(conn, scope, session_id, row_id):
    row = conn.execute(select(messages).where(where(scope, [session_id]), messages.c.id == row_id)).mappings().one_or_none()
    return decoded_row(row) if row else None


def visible():
    return or_(messages.c.active == 1, messages.c.compacted == 1)


def display_set(conn, scope, session_ids):
    """Visible bodies plus only the removed identities needed to suppress superseded copies."""
    from hermes_db.domains.sessions.postgres.support.message_codec import content_from_bytes
    rows = select_rows(conn, scope, session_ids, visible())
    names = ('session_id', 'id', 'role', 'timestamp', 'tool_call_id', 'tool_calls', 'tool_name',
             'display_kind', 'display_metadata', 'message_uid', 'absorbed_message_uids',
             'display_identity', 'active', 'compacted')
    removed = select(*(messages.c[name] for name in names),
        case((messages.c.display_identity.is_(None), messages.c.content), else_=None).label('content')).where(
            where(scope, session_ids), messages.c.active == 0, messages.c.compacted == 0)
    for row in conn.execute(removed).mappings():
        rows.append({**row, 'content': content_from_bytes(row['content'])})
    return sorted(rows, key=lambda row: row['id'])


def insert_row(conn, scope, row):
    values = stored_values(row)
    values.update(store_id=scope.require_store_id(), preview_text=preview_text(row), search_content=content_text(row))
    values["search_document"], values["search_grams"] = projection(row)
    values["spillover_names"] = spillover_names(row)
    values["roster_preview"] = roster_preview(row)
    values['display_query'] = display_projection(row.get('display_metadata'))
    row_id = conn.scalar(insert(messages).values(**values).returning(messages.c.id))
    identity = row["display_identity"]
    order = conn.scalar(select(func.min(messages.c.display_order)).where(where(scope, [row["session_id"]]),
        visible(), messages.c.display_identity == identity))
    conn.execute(messages.update().where(where(scope, [row["session_id"]]), messages.c.id == row_id)
                 .values(display_order=min(row_id, order) if order is not None else row_id))
    return row_id


def update_row(conn, scope, session_id, row_id, values):
    row = one(conn, scope, session_id, row_id)
    if row is None:
        return 0
    row.update(values)
    row["display_identity"] = codec._display_identity(codec._display_dedupe_key(row))
    encoded = stored_values(row)
    changes = {name: encoded[name] for name in values}
    if 'display_metadata' in values:
        changes['display_query'] = display_projection(row.get('display_metadata'))
    changes.update(display_identity=row["display_identity"], preview_text=preview_text(row), search_content=content_text(row))
    if {"content", "role", "tool_name", "tool_calls"}.intersection(values):
        changes["search_document"], changes["search_grams"] = projection(row)
    if {"content", "api_content"}.intersection(values):
        changes["spillover_names"] = spillover_names(row)
    if {"content", "role"}.intersection(values):
        changes["roster_preview"] = roster_preview(row)
    result = conn.execute(messages.update().where(where(scope, [session_id]), messages.c.id == row_id).values(**changes))
    reconcile_orders(conn, scope, session_id)
    bump_revision(conn, scope, session_id)
    return result.rowcount


def reconcile_orders(conn, scope, session_id):
    """Heal nullable legacy identities, then reconcile fixed-width identity/UID columns."""
    _backfill_missing_identities(conn, scope, session_id)
    columns = (messages.c.id, messages.c.display_identity, messages.c.message_uid, messages.c._compressed_summary, messages.c.display_order)
    rows = conn.execute(select(*columns).where(where(scope, [session_id]), visible()).order_by(messages.c.id)).mappings()
    first, uids, changes = {}, {}, []
    for row in rows:
        identity = row["display_identity"]
        if row["_compressed_summary"] and row["message_uid"]:
            identity = uids.get(row["message_uid"], identity)
        elif row["message_uid"]:
            uids.setdefault(row["message_uid"], identity)
        # Rewrites keep their old display slot beside an archived twin. New
        # generations join the identity's existing slot rather than moving it.
        first.setdefault(identity, row["display_order"] if row["display_order"] is not None else row["id"])
        if identity != row["display_identity"] or first[identity] != row["display_order"]:
            changes.append((row["id"], identity, first[identity]))
    for row_id, identity, order in changes:
        conn.execute(messages.update().where(where(scope, [session_id]), messages.c.id == row_id)
                     .values(display_identity=identity, display_order=order))


def _backfill_missing_identities(conn, scope, session_id):
    last_id = 0
    while True:
        rows = select_rows(conn, scope, [session_id], visible(), messages.c.display_identity.is_(None),
                           messages.c.id > last_id, limit=1000)
        if not rows:
            return
        for row in rows:
            identity = codec._display_identity(codec._display_dedupe_key(row))
            # A slot computed without an identity may already combine unrelated messages.
            conn.execute(messages.update().where(where(scope, [session_id]), messages.c.id == row['id'])
                         .values(display_identity=identity, display_order=None))
        last_id = rows[-1]['id']


def bump_revision(conn, scope, session_id, *, display_change=True):
    values = {"transcript_revision": sessions.c.transcript_revision + 1}
    if display_change:
        values["transcript_edit_revision"] = sessions.c.transcript_edit_revision + 1
    session_repo.update_session(conn, scope, session_id, values)


def bump_counters(conn, scope, session_id, inserted, tool_calls):
    session_repo.update_session(conn, scope, session_id, {
        "message_count": sessions.c.message_count + inserted, "tool_call_count": sessions.c.tool_call_count + tool_calls})
    if inserted:
        bump_revision(conn, scope, session_id, display_change=False)


def active_ids(conn, scope, session_id):
    return list(conn.execute(select(messages.c.id).where(where(scope, [session_id]), messages.c.active == 1)
                             .order_by(messages.c.id)).scalars())


def resume_lineage(conn, scope, session_id):
    rows = session_repo.lineage_rows(conn, scope, session_id)
    by_id = {row["id"]: row for row in rows}
    current, chain = by_id.get(session_id), [session_id]
    while current and current["parent_session_id"] in by_id:
        parent = by_id[current["parent_session_id"]]
        if parent["end_reason"] != "compression":
            break
        if parent["id"] in chain:
            raise ValueError("Conversation lineage contains a cycle")
        chain.append(parent["id"])
        current = parent
    return chain[::-1]
