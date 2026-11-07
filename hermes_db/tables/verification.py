"""Passive verification ledger, exact text keys and store-scoped references."""

from sqlalchemy import BigInteger, Column, Identity, Index, LargeBinary, Text

from hermes_db.tables.metadata import scoped_fk, scoped_table

verification_locks = scoped_table("verification_locks", key=())
verification_events = scoped_table("verification_events",
    Column("id", BigInteger, Identity(), nullable=False), Column("created_at", Text, nullable=False),
    *[Column(name, LargeBinary, nullable=False) for name in
      ("session_id", "cwd", "root", "command", "canonical_command", "output_summary")],
    *[Column(name, Text, nullable=False) for name in ("kind", "scope", "status")],
    Column("exit_code", BigInteger, nullable=False), key=("id",))
verification_state = scoped_table("verification_state",
    Column("session_id", LargeBinary, nullable=False), Column("root", LargeBinary, nullable=False),
    Column("last_event_id", BigInteger), Column("last_edit_at", Text),
    Column("changed_paths_json", Text, nullable=False, server_default="[]"), key=("session_id", "root"),
    constraints=(scoped_fk(("last_event_id",), "verification_events", ("id",), ondelete="RESTRICT"),))
Index("ix_verification_store_session_root", verification_events.c.store_id, verification_events.c.session_id,
      verification_events.c.root, verification_events.c.id)
Index("ix_verification_store_root", verification_events.c.store_id, verification_events.c.root, verification_events.c.id)
