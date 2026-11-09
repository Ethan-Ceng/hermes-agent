"""Peer recovery selectors with store fences on every correlated subquery."""

import time
from collections import Counter

from sqlalchemy import func, or_, select

from hermes_db.domains.sessions.postgres.queries import sessions as repo
from hermes_db.domains.sessions.postgres.queries.session_queries import last_activity
from hermes_db.tables.conversations import messages, sessions
from hermes_db.domains.sessions.rules import _RECOVERABLE_END_REASONS, _RESET_END_REASONS

PEER_FIELDS = ("user_id", "chat_id", "chat_type", "thread_id")


def has_messages(table=sessions):
    return select(messages.c.id).where(messages.c.store_id == table.c.store_id,
        messages.c.session_id == table.c.id).correlate(table).exists()


def newest_ids(conn, scope, *, platform=None, active_only=True):
    other = sessions.alias("newest")
    newest = select(func.max(other.c.started_at)).where(other.c.store_id == sessions.c.store_id,
        other.c.session_key == sessions.c.session_key).correlate(sessions).scalar_subquery()
    conditions = [sessions.c.store_id == scope.require_store_id(), sessions.c.session_key.is_not(None),
                  sessions.c.started_at == newest]
    if platform:
        conditions.append(func.lower(sessions.c.source) == platform.lower())
    if active_only:
        conditions.append(sessions.c.ended_at.is_(None))
    return list(conn.execute(select(sessions.c.id).where(*conditions).order_by(last_activity(conn).desc())).scalars())


def peer_candidate(conn, scope, *, source, session_key, owner, user_id=None, chat_id=None, chat_type=None, thread_id=None):
    values = dict(user_id=user_id, chat_id=chat_id, chat_type=chat_type, thread_id=thread_id)
    common = [sessions.c.store_id == scope.require_store_id(), sessions.c.source == source,
        or_(sessions.c.ended_at.is_(None), sessions.c.end_reason.in_(_RECOVERABLE_END_REASONS), sessions.c.handoff_state == "completed")]
    for by_key in (True, False):
        if not by_key and (chat_id is None or chat_type is None):
            return None
        boundary = sessions.alias("boundary")
        boundary_conditions = [boundary.c.store_id == sessions.c.store_id, boundary.c.source == sessions.c.source,
            boundary.c.ended_at.is_not(None), boundary.c.end_reason.in_(_RESET_END_REASONS),
            boundary.c.ended_at > func.coalesce(sessions.c.last_activity_at, sessions.c.started_at)]
        if by_key:
            extra = [sessions.c.session_key == session_key]
            boundary_conditions.append(boundary.c.session_key == sessions.c.session_key)
        else:
            extra = [func.coalesce(sessions.c[name], "") == (values[name] or "") for name in PEER_FIELDS]
            extra += _profile(sessions, owner, owner)
            extra.append(or_(sessions.c.message_count > 0, has_messages()))
            boundary_conditions.extend(func.coalesce(boundary.c[name], "") == func.coalesce(sessions.c[name], "") for name in PEER_FIELDS)
            boundary_conditions += _profile(boundary, owner, owner)
        extra.append(~select(boundary.c.id).where(*boundary_conditions).correlate(sessions).exists())
        order = [func.coalesce(sessions.c.last_activity_at, sessions.c.started_at).desc()]
        if by_key:
            order.insert(0, or_(sessions.c.message_count > 0, has_messages()).desc())
        found = conn.execute(select(sessions.c.id, or_(sessions.c.message_count > 0, has_messages()).label("_has_messages"))
            .where(*common, *extra).order_by(*order).limit(1)).mappings().one_or_none()
        if found is not None:
            return dict(repo.get_session(conn, scope, found["id"]), _has_messages=found["_has_messages"])
    return None


def _profile(table, owner, effective):
    return [] if owner is None else [func.coalesce(table.c.profile_name, owner) == effective]


def never_active(conn, scope, older_than_days):
    if older_than_days < 0:
        raise ValueError("older_than_days must be >= 0")
    empty = ("message_count", "tool_call_count", "api_call_count", "input_tokens", "output_tokens", "pinned", "archived")
    fields = ("id", "session_key", "source", "chat_id", "chat_type", "user_id", "started_at")
    conditions = [sessions.c.store_id == scope.require_store_id(), sessions.c.session_key.is_not(None),
        sessions.c.ended_at.is_(None), sessions.c.title.is_(None), sessions.c.last_activity_at.is_(None),
        sessions.c.started_at < time.time() - float(older_than_days) * 86400, ~has_messages()]
    conditions.extend(func.coalesce(sessions.c[name], 0) == 0 for name in empty)
    return [dict(row) for row in conn.execute(select(*(sessions.c[name] for name in fields)).where(*conditions)
        .order_by(sessions.c.started_at)).mappings()]


def orphan_candidates(conn, scope):
    count = select(func.count()).select_from(messages).where(messages.c.store_id == sessions.c.store_id,
        messages.c.session_id == sessions.c.id).correlate(sessions).scalar_subquery()
    conditions = (sessions.c.store_id == scope.require_store_id(), sessions.c.session_key.is_(None), has_messages(),
        func.coalesce(sessions.c.source, "") != "tool", sessions.c.has_branch_marker == 0,
        sessions.c.has_delegate_marker == 0)
    return [dict(row) for row in conn.execute(select(sessions, last_activity(conn).label("last_active"), count.label("actual_count"))
        .where(*conditions).order_by(sessions.c.started_at)).mappings()]


def orphan_donors(conn, scope, orphan, owner, gap):
    conditions = [sessions.c.store_id == scope.require_store_id(), sessions.c.session_key.is_not(None),
        func.coalesce(sessions.c.source, "") == (orphan["source"] or ""),
        *_profile(sessions, owner, orphan["profile_name"] or owner)]
    if orphan["parent_session_id"]:
        return list(conn.execute(select(sessions).where(*conditions,
            sessions.c.id == orphan["parent_session_id"])).mappings())
    activity, started = last_activity(conn), orphan["started_at"] or 0
    conditions += [sessions.c.id != orphan["id"],
        or_(func.coalesce(sessions.c.user_id, "") == "", (orphan["user_id"] or "") == "", sessions.c.user_id == orphan["user_id"]),
        activity.between(started - gap, started + gap), activity < orphan["last_active"]]
    return list(conn.execute(select(sessions).where(*conditions).order_by(activity.desc()).limit(2)).mappings())


def orphans(conn, scope, *, owner, max_gap_s=900):
    records = []
    for orphan in orphan_candidates(conn, scope):
        donors = orphan_donors(conn, scope, orphan, owner, max_gap_s)
        donor = donors[0] if len(donors) == 1 else None
        lineage = bool(orphan["parent_session_id"])
        reason = ""
        if not donor:
            reason = ("parent session carries no gateway identity of this source" if lineage else
                "ambiguous: more than one keyed predecessor matches this window" if donors else
                f"no keyed predecessor fell quiet within {max_gap_s:.0f}s of this session's start")
        records.append(dict(orphan_id=orphan["id"], source=orphan["source"], message_count=orphan["actual_count"],
            started_at=orphan["started_at"], last_active=orphan["last_active"], donor_id=donor["id"] if donor else None,
            session_key=donor["session_key"] if donor else None, evidence=("lineage" if lineage else "contiguity") if donor else "",
            adoptable=donor is not None, reason=reason))
    counts = Counter(row["donor_id"] for row in records if row["adoptable"])
    for row in records:
        if counts[row["donor_id"]] > 1:
            row.update(adoptable=False, reason="ambiguous: more than one unkeyed session claims this predecessor")
    return records
