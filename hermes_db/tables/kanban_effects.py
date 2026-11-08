"""Replayable post-commit work; primary transitions and their outbox intent share a commit."""

from sqlalchemy import BigInteger, Column, Float, LargeBinary, Text
from hermes_db.tables.metadata import scoped_fk, scoped_table

effects = scoped_table("kanban_postcommit_effects", Column("board_id", Text, nullable=False),
    Column("effect_id", Text, nullable=False), Column("owner_home", LargeBinary, nullable=False),
    Column("payload", LargeBinary, nullable=False), Column("phase", BigInteger, nullable=False, server_default="0"),
    Column("claim", Text), Column("expires_at", Float), key=("board_id", "effect_id"),
    constraints=(scoped_fk(("board_id",), "kanban_boards", ("board_id",), ondelete="CASCADE"),))
