"""Immutable Board generations, scoped tasks and dependency graph records."""

from sqlalchemy import BigInteger, Column, ForeignKeyConstraint, Identity, Index, LargeBinary, Text
from hermes_db.tables.metadata import SCHEMA, scoped_fk, scoped_table

kanban_board_locks = scoped_table("kanban_board_locks", key=())
kanban_boards = scoped_table("kanban_boards", Column("board_id", Text, nullable=False),
    Column("slug", Text, nullable=False),
    Column("archived", BigInteger, nullable=False, server_default="0"), key=("board_id",))
kanban_board_names = scoped_table("kanban_board_names", Column("slug", Text, nullable=False),
    Column("board_id", Text, nullable=False), key=("slug",),
    constraints=(scoped_fk(("board_id",), "kanban_boards", ("board_id",), ondelete="CASCADE"),))

TASK_TEXT_FIELDS = (
    "id", "title", "body", "assignee", "status", "created_by", "workspace_kind", "workspace_path",
    "claim_lock", "tenant", "branch_name", "project_id", "result", "idempotency_key", "last_failure_error",
    "workflow_template_id", "current_step_key", "skills", "model_override", "provider_override",
    "reasoning_effort", "session_id", "block_kind", "completion_contract", "worker_started_at",
)
TASK_NUMBER_FIELDS = (
    "created_at", "started_at", "completed_at", "claim_expires", "last_heartbeat_at", "worker_pid",
    "max_runtime_seconds", "current_run_id", "max_retries", "goal_max_turns",
)
tasks = scoped_table("kanban_tasks", Column("board_id", Text, nullable=False),
    *[Column(name, LargeBinary, nullable=name not in {"id", "title", "status", "workspace_kind"}) for name in TASK_TEXT_FIELDS],
    *[Column(name, BigInteger) for name in TASK_NUMBER_FIELDS],
    *[Column(name, BigInteger, nullable=False, server_default="0") for name in
      ("priority", "consecutive_failures", "goal_mode", "block_recurrences")],
    key=("board_id", "id"), constraints=(scoped_fk(("board_id",), "kanban_boards", ("board_id",), ondelete="CASCADE"),))
links = scoped_table("kanban_links", Column("board_id", Text, nullable=False),
    Column("parent_id", LargeBinary, nullable=False), Column("child_id", LargeBinary, nullable=False),
    key=("board_id", "parent_id", "child_id"), constraints=(
        scoped_fk(("board_id", "parent_id"), "kanban_tasks", ("board_id", "id"), ondelete="CASCADE"),
        ForeignKeyConstraint(["store_id", "board_id", "child_id"],
            [f"{SCHEMA}.kanban_tasks.{name}" for name in ("store_id", "board_id", "id")],
            name="fk_kanban_links_child_task", ondelete="CASCADE")))
comments = scoped_table("kanban_comments", Column("board_id", Text, nullable=False),
    Column("id", BigInteger, Identity(), nullable=False), Column("task_id", LargeBinary, nullable=False),
    Column("author", LargeBinary, nullable=False), Column("body", LargeBinary, nullable=False),
    Column("created_at", BigInteger, nullable=False), key=("board_id", "id"),
    constraints=(scoped_fk(("board_id", "task_id"), "kanban_tasks", ("board_id", "id"), ondelete="CASCADE"),))
events = scoped_table("kanban_events", Column("board_id", Text, nullable=False),
    Column("id", BigInteger, Identity(), nullable=False), Column("task_id", LargeBinary, nullable=False),
    Column("kind", LargeBinary, nullable=False), Column("payload", LargeBinary),
    Column("created_at", BigInteger, nullable=False), Column("run_id", BigInteger), key=("board_id", "id"),
    constraints=(scoped_fk(("board_id", "task_id"), "kanban_tasks", ("board_id", "id"), ondelete="CASCADE"),))
Index("ix_kanban_tasks_status", tasks.c.store_id, tasks.c.board_id, tasks.c.status)
Index("ix_kanban_links_child", links.c.store_id, links.c.board_id, links.c.child_id)
Index("ix_kanban_comments_task", comments.c.store_id, comments.c.board_id, comments.c.task_id, comments.c.created_at)
Index("ix_kanban_events_task", events.c.store_id, events.c.board_id, events.c.task_id, events.c.id)
