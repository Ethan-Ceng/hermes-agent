"""Mutation receipts are owned by the same store and Board as their business effect."""

from sqlalchemy import BigInteger, Column, LargeBinary, Text

from hermes_db.tables.metadata import scoped_fk, scoped_table

command_receipts = scoped_table("kanban_command_receipts", Column("board_id", Text, nullable=False),
    Column("command_id", Text, nullable=False), Column("request_digest", Text, nullable=False),
    Column("result", LargeBinary, nullable=False), Column("created_at", BigInteger, nullable=False),
    key=("board_id", "command_id"),
    constraints=(scoped_fk(("board_id",), "kanban_boards", ("board_id",), ondelete="CASCADE"),))
