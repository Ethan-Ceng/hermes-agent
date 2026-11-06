"""Routes and coordination rows survive independently of prunable transcripts."""

from sqlalchemy import BigInteger, Column, Double, Index, LargeBinary, Text, UniqueConstraint

from hermes_db.tables.metadata import scoped_fk, scoped_table, text_columns, zero_columns

gateway_routing = scoped_table("gateway_routing", Column("scope", Text, nullable=False, server_default=""),
    Column("session_key", Text, nullable=False), Column("entry_json", Text, nullable=False),
    Column("updated_at", Double, nullable=False), key=("scope", "session_key"))
gateway_hygiene_state = scoped_table("gateway_hygiene_state", Column("session_key", Text, nullable=False),
    *zero_columns("failure_streak"), key=("session_key",))
conversation_generations = scoped_table("conversation_generations", Column("source", Text, nullable=False),
    Column("session_key", Text, nullable=False), *zero_columns("generation"), key=("source", "session_key"))
gateway_heartbeats = scoped_table("gateway_heartbeats", Column("backend_id", Text, nullable=False),
    Column("pid", BigInteger, nullable=False), Column("started_at", Double, nullable=False),
    Column("last_heartbeat", Double, nullable=False),
    Column("profile", Text, nullable=False, server_default=""), Column("host", Text, nullable=False, server_default=""),
    key=("backend_id",))


def _lease_table(name, identity):
    table = scoped_table(name, Column(identity, Text, nullable=False), Column("holder", Text, nullable=False),
                         Column("acquired_at", Double, nullable=False), Column("expires_at", Double, nullable=False),
                         key=(identity,))
    Index(f"ix_{name}_store_expiry", table.c.store_id, table.c.expires_at)
    return table


compression_locks = _lease_table("compression_locks", "session_id")
session_turn_leases = _lease_table("session_turn_leases", "conversation_id")
async_delegations = scoped_table(
    "async_delegations", Column("delegation_id", Text, nullable=False), Column("origin_session", Text, nullable=False),
    Column("origin_ui_session_id", Text, nullable=False, server_default=""),
    Column("origin_session_id", Text, nullable=False, server_default=""), Column("state", Text, nullable=False),
    *text_columns("parent_session_id", "event_json", "result_json", "task_json", "owner_execution_id", "delivery_claim"),
    Column("dispatched_at", Double, nullable=False), Column("updated_at", Double, nullable=False),
    Column("completed_at", Double), Column("delivered_at", Double), Column("delivery_claimed_at", Double),
    Column("owner_pid", BigInteger), Column("owner_started_at", BigInteger),
    Column("delivery_state", Text, nullable=False, server_default="pending"), *zero_columns("delivery_attempts"),
    key=("delegation_id",),
)
Index("ix_delegations_store_delivery", async_delegations.c.store_id, async_delegations.c.delivery_state,
      async_delegations.c.completed_at)
delivery_obligations = scoped_table(
    "delivery_obligations", Column("obligation_id", Text, nullable=False),
    *text_columns("session_key", "platform", "chat_id", "state", nullable=False),
    *text_columns("thread_id", "adapter_profile"), Column("content", LargeBinary, nullable=False),
    Column("last_error", LargeBinary), *zero_columns("attempts"),
    Column("created_at", Double, nullable=False), Column("updated_at", Double, nullable=False),
    Column("owner_pid", BigInteger), Column("owner_started_at", BigInteger),
    Column("claim_token", Text), Column("claim_expires_at", Double), Column("owner_instance_id", Text),
    key=("obligation_id",),
)
Index("ix_deliveries_store_state", delivery_obligations.c.store_id, delivery_obligations.c.state,
      delivery_obligations.c.updated_at)

telegram_dm_topic_mode = scoped_table("telegram_dm_topic_mode",
    Column("profile_name", Text, nullable=False, server_default="default"),
    *text_columns("chat_id", "user_id", nullable=False),
    Column("enabled", BigInteger, nullable=False, server_default="1"),
    Column("activated_at", Double, nullable=False), Column("updated_at", Double, nullable=False),
    Column("has_topics_enabled", BigInteger), Column("allows_users_to_create_topics", BigInteger),
    Column("capability_checked_at", Double), *text_columns("intro_message_id", "pinned_message_id"),
    key=("profile_name", "chat_id"))
telegram_dm_topic_bindings = scoped_table("telegram_dm_topic_bindings",
    Column("profile_name", Text, nullable=False, server_default="default"),
    *text_columns("chat_id", "thread_id", "user_id", "session_key", "session_id", nullable=False),
    Column("managed_mode", Text, nullable=False, server_default="auto"),
    Column("linked_at", Double, nullable=False), Column("updated_at", Double, nullable=False),
    key=("profile_name", "chat_id", "thread_id"), constraints=(
        scoped_fk(("session_id",), "sessions", ("id",), ondelete="CASCADE"),
        UniqueConstraint("store_id", "session_id", name="uq_topic_binding_store_session"),
    ))
Index("ix_topic_binding_store_user", telegram_dm_topic_bindings.c.store_id,
      telegram_dm_topic_bindings.c.profile_name, telegram_dm_topic_bindings.c.user_id,
      telegram_dm_topic_bindings.c.chat_id)
