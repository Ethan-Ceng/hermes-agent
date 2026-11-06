"""Response continuity and durable Run request identities in the same store."""

from sqlalchemy import BigInteger, Column, Double, Index, Text, UniqueConstraint

from hermes_db.tables.metadata import scoped_fk, scoped_table

# api_scope is separate from store_id: service authorization can subdivide a
# logical store without collapsing the existing API idempotency namespaces.
responses = scoped_table("responses", Column("api_scope", Text, nullable=False),
    Column("response_id", Text, nullable=False), Column("data", Text, nullable=False),
    Column("accessed_at", Double, nullable=False), key=("api_scope", "response_id"))
conversations = scoped_table("conversations", Column("api_scope", Text, nullable=False),
    Column("name", Text, nullable=False), Column("response_id", Text, nullable=False), key=("api_scope", "name"))
# Conversation mappings and keys may outlive LRU bodies. Deliberately no FK
# to responses: body eviction must not re-open accepted request identities.
response_keys = scoped_table("response_keys", Column("api_scope", Text, nullable=False),
    Column("request_key", Text, nullable=False), Column("fingerprint", Text, nullable=False),
    Column("created_at", BigInteger, nullable=False), Column("model_json", Text),
    Column("settled_at", Double), Column("response_id", Text), key=("api_scope", "request_key"))
response_admissions = scoped_table("response_admissions", Column("api_scope", Text, nullable=False),
    Column("request_key", Text, nullable=False), Column("admission_id", Text, nullable=False),
    key=("api_scope", "request_key"), constraints=(
        scoped_fk(("api_scope", "request_key"), "response_keys", ("api_scope", "request_key"), ondelete="CASCADE"),
    ))
response_output_order = scoped_table("response_output_order", Column("api_scope", Text, nullable=False),
    Column("request_key", Text, nullable=False), Column("item_id", Text, nullable=False),
    Column("output_index", BigInteger, nullable=False), key=("api_scope", "request_key", "item_id"), constraints=(
        scoped_fk(("api_scope", "request_key"), "response_keys", ("api_scope", "request_key"), ondelete="CASCADE"),
        UniqueConstraint("store_id", "api_scope", "request_key", "output_index", name="uq_response_output_store_index"),
    ))
run_idempotency = scoped_table("run_idempotency", Column("scope", Text, nullable=False),
    Column("idempotency_key", Text, nullable=False), Column("fingerprint", Text, nullable=False),
    Column("run_id", Text, nullable=False), Column("status_json", Text, nullable=False),
    Column("owner_pid", BigInteger, nullable=False, server_default="0"),
    Column("owner_started", BigInteger, nullable=False, server_default="0"),
    Column("retention_until", Double, nullable=False, server_default="0"), Column("acknowledged_at", Double),
    Column("created_at", Double, nullable=False), Column("updated_at", Double, nullable=False),
    key=("scope", "idempotency_key"), constraints=(
        UniqueConstraint("store_id", "scope", "run_id", name="uq_run_idempotency_store_run"),
    ))
Index("ix_response_keys_store_settled", response_keys.c.store_id, response_keys.c.api_scope, response_keys.c.settled_at)
