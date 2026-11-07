"""Attachment metadata and a per-path fence for post-commit file cleanup."""

from sqlalchemy import BigInteger, Column, Identity, Index, LargeBinary, Text
from hermes_db.tables.metadata import scoped_fk, scoped_table

attachments = scoped_table("kanban_attachments", Column("board_id", Text, nullable=False),
    Column("id", BigInteger, Identity(), nullable=False), Column("task_id", LargeBinary, nullable=False),
    *[Column(name, LargeBinary, nullable=False) for name in ("filename", "stored_path")],
    Column("content_type", LargeBinary), Column("uploaded_by", LargeBinary),
    Column("size", BigInteger, nullable=False, server_default="0"), Column("created_at", BigInteger, nullable=False),
    key=("board_id", "id"), constraints=(scoped_fk(("board_id", "task_id"), "kanban_tasks", ("board_id", "id"), ondelete="CASCADE"),))
blobs = scoped_table("kanban_blobs", Column("path", LargeBinary, nullable=False), Column("cleanup_token", Text), key=("path",))
Index("ix_kanban_attachments_task", attachments.c.store_id, attachments.c.board_id, attachments.c.task_id, attachments.c.created_at)
Index("ix_kanban_attachments_path", attachments.c.store_id, attachments.c.stored_path)
