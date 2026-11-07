"""Durable local Board file obligations survive logical retirement and owner restart."""

from sqlalchemy import BigInteger, Column, LargeBinary, Text
from hermes_db.tables.metadata import scoped_table

file_locks = scoped_table("kanban_file_locks", key=())
file_jobs = scoped_table("kanban_file_jobs", Column("board_id", Text, nullable=False),
    Column("slug", Text, nullable=False), Column("action", Text, nullable=False),
    Column("state", Text, nullable=False, server_default="'pending'"),
    *[Column(name, LargeBinary, nullable=False) for name in ("owner_home", "data_root", "attachments_root", "workspaces_root", "logs_root")],
    Column("stage_root", LargeBinary), Column("created_at", BigInteger, nullable=False), key=("board_id",))
