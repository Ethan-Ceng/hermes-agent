"""Profile-scoped hosted room logs and independently durable replicas."""

from sqlalchemy import BigInteger, CheckConstraint, Column, Float, LargeBinary, Text, UniqueConstraint
from hermes_db.tables.metadata import scoped_fk, scoped_table

room_locks = scoped_table("hosted_room_store_locks", key=())
rooms = scoped_table("hosted_rooms", Column("room_id", Text, nullable=False),
    Column("name", LargeBinary, nullable=False), Column("members_json", LargeBinary, nullable=False),
    Column("authority_gateway_id", Text, nullable=False), Column("authority_epoch", BigInteger, nullable=False),
    Column("next_seq", BigInteger, nullable=False), Column("event_bytes", BigInteger, nullable=False),
    Column("revision", BigInteger, nullable=False), Column("created_at", Float, nullable=False),
    Column("updated_at", Float, nullable=False), Column("disbanded_at", Float), key=("room_id",),
    constraints=(CheckConstraint("authority_epoch >= 1 AND next_seq >= 1 AND revision >= 1", name="room_counters"),))
events = scoped_table("hosted_room_events", Column("room_id", Text, nullable=False), Column("seq", BigInteger, nullable=False),
    Column("event_id", LargeBinary, nullable=False), Column("kind", LargeBinary, nullable=False),
    Column("actor_json", LargeBinary, nullable=False), Column("authority_epoch", BigInteger),
    Column("payload_json", LargeBinary, nullable=False), Column("created_at", Float, nullable=False),
    Column("policy_thread_key", LargeBinary), Column("policy_discussion_key", LargeBinary), key=("room_id", "seq"),
    constraints=(UniqueConstraint("store_id", "room_id", "event_id"),
        scoped_fk(("room_id",), "hosted_rooms", ("room_id",), ondelete="CASCADE"),
        CheckConstraint("seq >= 1 AND (authority_epoch IS NULL OR authority_epoch >= 1)", name="event_counters")))
retired = scoped_table("hosted_room_retired_ids", Column("room_id", Text, nullable=False),
    Column("retired_at", Float, nullable=False), key=("room_id",))
replicas = scoped_table("hosted_room_replicas", Column("room_id", Text, nullable=False), Column("name", LargeBinary, nullable=False),
    Column("members_json", LargeBinary, nullable=False), Column("authority_gateway_id", Text, nullable=False),
    Column("authority_epoch", BigInteger, nullable=False), Column("last_seq", BigInteger, nullable=False),
    Column("latest_seq", BigInteger, nullable=False), Column("event_bytes", BigInteger, nullable=False),
    Column("created_at", Float, nullable=False), Column("updated_at", Float, nullable=False), key=("room_id",))
replica_events = scoped_table("hosted_room_replica_events", Column("room_id", Text, nullable=False),
    Column("seq", BigInteger, nullable=False), Column("event_id", LargeBinary, nullable=False), Column("kind", LargeBinary, nullable=False),
    Column("actor_json", LargeBinary, nullable=False), Column("authority_epoch", BigInteger),
    Column("payload_json", LargeBinary, nullable=False), Column("created_at", Float, nullable=False), key=("room_id", "seq"),
    constraints=(scoped_fk(("room_id",), "hosted_room_replicas", ("room_id",), ondelete="CASCADE"),))

links = scoped_table("hosted_room_links", *[Column(name, LargeBinary, nullable=False) for name in (
    "room_id", "member_id", "target_url", "target_profile", "grant", "catalog_json", "cancellation_scope_id",
    "trace_id", "transport_security", "status")], Column("updated_at", Float, nullable=False), key=("room_id", "member_id"))
# A revoke remains owed after its room is purged; only store retirement cascades it.
owed_revokes = scoped_table('hosted_room_owed_revokes', Column('room_id', LargeBinary, nullable=False),
    Column('member_id', LargeBinary, nullable=False), Column('grant_digest', Text, nullable=False),
    Column('target_url', LargeBinary, nullable=False), Column('grant', LargeBinary, nullable=False),
    Column('expires_at', Float, nullable=False), Column('next_attempt_at', Float, nullable=False),
    Column('created_at', Float, nullable=False), Column('attempts', BigInteger, nullable=False, server_default='0'),
    Column('held', BigInteger, nullable=False, server_default='0'), key=('room_id', 'member_id', 'grant_digest'),
    constraints=(CheckConstraint("expires_at > '-Infinity'::double precision AND expires_at < 'Infinity'::double precision",
        name='owed_revoke_finite_expiry').ddl_if(dialect='postgresql'),))
revoked_grants = scoped_table("hosted_room_revoked_grants", Column("scope_key", Text, nullable=False),
    Column("expires_at", Float, nullable=False), Column("revoked_before", Float, nullable=False), key=("scope_key",))
reservations = scoped_table("hosted_room_peer_reservations", *[Column(name, LargeBinary, nullable=False) for name in (
    "room_id", "member_id", "target_profile", "authority_gateway_id")], Column("authority_epoch", BigInteger, nullable=False),
    Column("expires_at", Float, nullable=False), Column("revoked_at", Float), Column("created_at", Float, nullable=False),
    Column("updated_at", Float, nullable=False), key=("room_id", "member_id", "target_profile"))
REMOTE_IDENTITY = ("room_id", "home_install_id", "authority_gateway_id", "authority_epoch", "member_id",
                   "target_install_id", "target_profile", "task_id", "execution_generation")
remote_runs = scoped_table("hosted_room_remote_runs", *[Column(name, BigInteger if name in {
    "authority_epoch", "execution_generation"} else LargeBinary, nullable=False) for name in (*REMOTE_IDENTITY, "run_id", "session_id")],
    Column("created_at", Float, nullable=False), Column("updated_at", Float, nullable=False), key=REMOTE_IDENTITY)
