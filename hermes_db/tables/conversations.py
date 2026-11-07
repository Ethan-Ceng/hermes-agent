"""Conversation, exact transcript, prompt snapshots, and multidimensional usage."""

from sqlalchemy import BigInteger, Column, Double, Identity, Index, JSON, LargeBinary, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR

from hermes_db.tables.metadata import scoped_fk, scoped_table, text_columns, zero_columns

# Roots outlive prunable transcript rows; absent/retired roots still have a
# stable row to lock. Forks create a new root, compression segments reuse it.
transcript_roots = scoped_table("transcript_roots", Column("root_id", Text, nullable=False), key=("root_id",))
system_prompts = scoped_table("system_prompts", Column("hash", Text, nullable=False),
                              Column("prompt", LargeBinary, nullable=False), key=("hash",))

sessions = scoped_table(
    "sessions", Column("id", Text, nullable=False), Column("lineage_root_id", Text, nullable=False),
    Column("source", Text, nullable=False), Column("started_at", Double, nullable=False),
    *text_columns("created_source", "user_id", "session_key", "chat_id", "chat_type", "thread_id", "origin_json",
                  "model", "model_config", "system_prompt_hash", "parent_session_id", "end_reason", "cwd",
                  "git_branch", "git_repo_root", "billing_provider", "billing_base_url", "billing_mode",
                  "cost_status", "cost_source", "pricing_version", "title_source", "last_activity_provenance",
                  "handoff_state", "handoff_platform", "profile_name", "transport_profile", "tool_names"),
    *[Column(name, LargeBinary) for name in ("system_prompt", "display_name", "title", "last_activity_description",
                                           "handoff_error", "compression_failure_error")],
    Column("title_search", Text), Column("delegate_origin", LargeBinary),
    *zero_columns("has_delegate_marker", "has_branch_marker"),
    *[Column(name, Double) for name in ("ended_at", "last_activity_at", "last_read_at", "estimated_cost_usd",
                                      "actual_cost_usd", "compression_failure_cooldown_until", "compression_recovery_deadline")],
    *zero_columns("runtime_revision", "runtime_generation", "git_metadata_generation", "transcript_revision",
                  "compression_fallback_streak", "compression_ineffective_count", "compression_overload_streak",
                  "rewind_count", "archived", "auto_archived", "pinned", "hidden"),
    *zero_columns("expiry_finalized", "message_count", "tool_call_count", "input_tokens", "output_tokens",
                  "cache_read_tokens", "cache_write_tokens", "reasoning_tokens", "api_call_count", nullable=True),
    key=("id",), constraints=(
        scoped_fk(("lineage_root_id",), "transcript_roots", ("root_id",), ondelete="RESTRICT"),
        scoped_fk(("parent_session_id",), "sessions", ("id",), ondelete="RESTRICT"),
        scoped_fk(("system_prompt_hash",), "system_prompts", ("hash",), ondelete="RESTRICT"),
        scoped_fk(("tool_names",), "system_prompts", ("hash",), ondelete="RESTRICT"),
    ),
)
Index("ix_sessions_store_source_started", sessions.c.store_id, sessions.c.source, sessions.c.started_at.desc(), sessions.c.id)
Index("ix_sessions_store_parent", sessions.c.store_id, sessions.c.parent_session_id)
Index("ix_sessions_store_root", sessions.c.store_id, sessions.c.lineage_root_id)
Index("uq_sessions_store_title", sessions.c.store_id, sessions.c.title, unique=True,
      postgresql_where=sessions.c.title.is_not(None), sqlite_where=sessions.c.title.is_not(None))

messages = scoped_table(
    "messages", Column("id", BigInteger, Identity(), nullable=False),
    Column("display_query", JSON().with_variant(JSONB, 'postgresql'), nullable=False, server_default='{}'),
    Column("session_id", Text, nullable=False), Column("role", Text, nullable=False),
    Column("timestamp", Double, nullable=False), Column("token_count", BigInteger),
    *text_columns("tool_call_id", "tool_calls", "tool_name", "effect_disposition", "finish_reason",
                  "platform_message_id", "display_kind", "display_metadata", "message_uid",
                  "absorbed_message_uids", "tool_call_uids", "tool_call_uid"),
    *[Column(name, LargeBinary) for name in ("content", "reasoning", "reasoning_content", "reasoning_details",
                                           "codex_reasoning_items", "codex_message_items", "api_content", "display_identity")],
    Column("display_order", BigInteger), Column("search_content", Text), Column("preview_text", LargeBinary),
    Column("search_document", Text), Column("search_grams", ARRAY(Text).with_variant(JSON, "sqlite")),
    Column("spillover_names", ARRAY(Text).with_variant(JSON, "sqlite")),
    Column("roster_preview", LargeBinary),
    *zero_columns("observed", nullable=True), *zero_columns("_compressed_summary", "compacted"),
    Column("active", BigInteger, nullable=False, server_default="1"),
    key=("id",), constraints=(scoped_fk(("session_id",), "sessions", ("id",), ondelete="RESTRICT"),),
)
Index("ix_messages_store_session_id", messages.c.store_id, messages.c.session_id, messages.c.id)
Index("ix_messages_store_session_time", messages.c.store_id, messages.c.session_id, messages.c.timestamp, messages.c.id)
Index("ix_messages_store_session_uid", messages.c.store_id, messages.c.session_id, messages.c.message_uid)
Index("ix_messages_store_display_order", messages.c.store_id, messages.c.session_id, messages.c.display_order)
Index("ix_messages_store_display_identity", messages.c.store_id, messages.c.session_id, messages.c.display_identity)
Index("ix_messages_search_trgm", messages.c.search_document, postgresql_using="gin",
      postgresql_ops={"search_document": "gin_trgm_ops"}).ddl_if(dialect="postgresql")
Index("ix_messages_search_grams", messages.c.search_grams, postgresql_using="gin").ddl_if(dialect="postgresql")
Index("ix_messages_store_spillover_refs", messages.c.store_id, messages.c.id,
      postgresql_where=messages.c.spillover_names.is_not(None)).ddl_if(dialect="postgresql")

message_search_chunks = scoped_table("message_search_chunks", Column("message_id", BigInteger, nullable=False),
    Column("chunk", BigInteger, nullable=False), Column("search_vector", TSVECTOR().with_variant(Text, "sqlite"), nullable=False),
    key=("message_id", "chunk"), constraints=(scoped_fk(("message_id",), "messages", ("id",), ondelete="CASCADE"),))
Index("ix_message_search_chunks_fts", message_search_chunks.c.search_vector, postgresql_using="gin").ddl_if(dialect="postgresql")

session_model_usage = scoped_table(
    "session_model_usage", Column("session_id", Text, nullable=False), Column("model", Text, nullable=False),
    *[Column(name, Text, nullable=False, server_default="") for name in (
        "billing_provider", "billing_base_url", "billing_mode", "task")],
    *zero_columns("api_call_count", "input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "reasoning_tokens"),
    Column("usage_order", BigInteger, nullable=False, server_default="0"),
    Column("estimated_cost_usd", Double, nullable=False, server_default="0"),
    Column("actual_cost_usd", Double, nullable=False, server_default="0"),
    *text_columns("cost_status", "cost_source"), Column("first_seen", Double), Column("last_seen", Double),
    key=("session_id", "model", "billing_provider", "billing_base_url", "billing_mode", "task"),
    constraints=(scoped_fk(("session_id",), "sessions", ("id",), ondelete="CASCADE"),),
)
