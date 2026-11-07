"""Scoped bounded policy caches; opaque JSON identities remain lossless bytes."""

from sqlalchemy import BigInteger, CheckConstraint, Column, Float, LargeBinary, Text
from hermes_db.tables.metadata import scoped_fk, scoped_table


def _room_table(name, *columns, key=()):
    return scoped_table(name, Column("room_id", Text, nullable=False), *columns,
        key=("room_id", *key), constraints=(scoped_fk(("room_id",), "hosted_rooms", ("room_id",), ondelete="CASCADE"),))


capacity = scoped_table("hosted_room_policy_capacity", Column("singleton", BigInteger, nullable=False),
    Column("max_active_events", BigInteger, nullable=False), key=("singleton",),
    constraints=(CheckConstraint("singleton=1", name="room_policy_singleton"),
        CheckConstraint("max_active_events>=1", name="room_policy_capacity")))
cursors = _room_table("hosted_room_policy_cursors", Column("through_seq", BigInteger, nullable=False),
    Column("stopped_through_seq", BigInteger, nullable=False), Column("updated_at", Float, nullable=False))
threads = _room_table("hosted_room_policy_threads", Column("thread_id", LargeBinary, nullable=False),
    Column("discussion_event_id", LargeBinary, nullable=False), Column("latest_user_seq", BigInteger, nullable=False),
    Column("completed", BigInteger, nullable=False), key=("thread_id",))
active = _room_table("hosted_room_policy_events", Column("thread_id", LargeBinary, nullable=False),
    Column("discussion_event_id", LargeBinary, nullable=False), Column("seq", BigInteger, nullable=False),
    Column("event_json", LargeBinary, nullable=False), Column("kind", Text, nullable=False), key=("seq",))
watermarks = _room_table("hosted_room_policy_watermarks", Column("thread_id", LargeBinary, nullable=False),
    Column("member_id", LargeBinary, nullable=False), Column("seen_through_seq", BigInteger, nullable=False), key=("thread_id", "member_id"))
transcript = _room_table("hosted_room_policy_transcript", Column("thread_id", LargeBinary, nullable=False),
    Column("seq", BigInteger, nullable=False), Column("kind", Text, nullable=False), Column("settled_seq", BigInteger), key=("thread_id", "seq"))
transcript_state = _room_table("hosted_room_policy_transcript_state", Column("schema_version", BigInteger, nullable=False))
router_claims = scoped_table("hosted_room_router_claims", Column("room_id", Text, nullable=False),
    Column("discussion_event_id", LargeBinary, nullable=False), Column("owner", Text, nullable=False),
    Column("expires_at", Float, nullable=False), key=("room_id", "discussion_event_id"))
