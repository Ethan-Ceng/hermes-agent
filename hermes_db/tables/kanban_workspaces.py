"""Canonical local workspace references and durable deletion fences."""

from sqlalchemy import Column, Index, LargeBinary, Text
from hermes_db.tables.metadata import scoped_fk, scoped_table

paths = scoped_table("kanban_workspace_paths", Column("path_key", LargeBinary, nullable=False),
    Column("cleanup_token", Text), key=("path_key",))
references = scoped_table("kanban_workspace_refs", Column("board_id", Text, nullable=False),
    Column("task_id", LargeBinary, nullable=False), Column("path_key", LargeBinary, nullable=False),
    key=("board_id", "task_id"), constraints=(
        scoped_fk(("board_id", "task_id"), "kanban_tasks", ("board_id", "id"), ondelete="CASCADE"),
        scoped_fk(("path_key",), "kanban_workspace_paths", ("path_key",)),))
Index("ix_kanban_workspace_refs_path", references.c.store_id, references.c.path_key)
