"""Matrix protocol storage; every identity includes Profile, account realm and own device."""

from sqlalchemy import BigInteger, Column, Float, Index, LargeBinary, Text
from hermes_db.tables.metadata import scoped_table, scoped_fk


def _table(name, *columns, key=()):
    constraints = () if name == "matrix_roots" else (scoped_fk(("account_key", "owner_device"), "matrix_roots", ("account_key", "owner_device"), ondelete="RESTRICT"),)
    return scoped_table(name, Column("account_key", LargeBinary, nullable=False), Column("owner_device", LargeBinary, nullable=False),
        *columns, key=("account_key", "owner_device", *key), constraints=constraints)


roots = _table("matrix_roots", Column("generation", Text, nullable=False), Column("device_id", LargeBinary),
    Column("sync_token", LargeBinary), Column("account_pickle", LargeBinary), Column("identity_key", LargeBinary), Column("shared", BigInteger, nullable=False, server_default="0"))
olm_sessions = _table("matrix_olm_sessions", Column("sender_key", LargeBinary, nullable=False), Column("session_id", LargeBinary, nullable=False),
    Column("pickle", LargeBinary, nullable=False), *[Column(name, LargeBinary) for name in ("created_at", "last_encrypted", "last_decrypted")],
    Column("decrypted_order", Float), key=("sender_key", "session_id"))
inbound = _table("matrix_inbound_sessions", Column("room_id", LargeBinary, nullable=False), Column("session_id", LargeBinary, nullable=False),
    *[Column(name, LargeBinary) for name in ("sender_key", "signing_key", "pickle", "forwarding_json", "ratchet_json", "received_at", "withheld_reason", "max_age_json")],
    Column("received_order", Float), Column("max_age_ms", Float), Column("max_messages", BigInteger),
    Column("is_scheduled", BigInteger, nullable=False, server_default="0"), Column("withheld_code", Text), key=("room_id", "session_id"))
outbound = _table("matrix_outbound_sessions", Column("room_id", LargeBinary, nullable=False), Column("session_id", LargeBinary, nullable=False),
    Column("pickle", LargeBinary, nullable=False), Column("shared", BigInteger, nullable=False), Column("max_age_ms", Float, nullable=False), Column("max_age_json", LargeBinary, nullable=False),
    Column("max_messages", BigInteger, nullable=False), Column("message_count", BigInteger, nullable=False),
    Column("created_at", LargeBinary, nullable=False), Column("last_used", LargeBinary, nullable=False), key=("room_id",))
message_indices = _table("matrix_message_indices", Column("sender_key", LargeBinary, nullable=False), Column("session_id", LargeBinary, nullable=False),
    Column("message_index", BigInteger, nullable=False), Column("event_id", LargeBinary, nullable=False), Column("timestamp", BigInteger, nullable=False), key=("sender_key", "session_id", "message_index"))
tracked_users = _table("matrix_tracked_users", Column("user_id", LargeBinary, nullable=False), key=("user_id",))
devices = _table("matrix_devices", *[Column(name, LargeBinary, nullable=False) for name in ("user_id", "device_id", "identity_key", "signing_key")],
    Column("trust", BigInteger, nullable=False), Column("deleted", BigInteger, nullable=False), Column("name", LargeBinary), key=("user_id", "device_id"))
cross_signing = _table("matrix_cross_signing", Column("user_id", LargeBinary, nullable=False), Column("usage", Text, nullable=False),
    Column("key", LargeBinary, nullable=False), Column("first_key", LargeBinary, nullable=False), key=("user_id", "usage"))
signatures = _table("matrix_signatures", *[Column(name, LargeBinary, nullable=False) for name in ("target_user", "target_key", "signer_user", "signer_key", "signature")],
    key=("target_user", "target_key", "signer_user", "signer_key"))
Index("idx_matrix_inbound_expiry", inbound.c.store_id, inbound.c.account_key, inbound.c.owner_device, inbound.c.received_order)
Index("idx_matrix_olm_latest", olm_sessions.c.store_id, olm_sessions.c.account_key, olm_sessions.c.owner_device, olm_sessions.c.sender_key, olm_sessions.c.decrypted_order)
