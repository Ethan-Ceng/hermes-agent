"""Durable Board subscription routes and independently retryable delivery cursors."""

from sqlalchemy import BigInteger, Column, LargeBinary, Text
from hermes_db.tables.metadata import scoped_fk, scoped_table

TEXT_FIELDS = ("task_id", "platform", "chat_id", "thread_id", "user_id", "user_id_alt", "chat_type",
               "notifier_profile", "delivery_mode", "delivery_metadata")
subscriptions = scoped_table("kanban_notify_subs", Column("board_id", Text, nullable=False),
    *[Column(name, LargeBinary, nullable=name not in {"task_id", "platform", "chat_id", "thread_id", "delivery_mode"}) for name in TEXT_FIELDS],
    Column("platform_key", LargeBinary, nullable=False), Column("created_at", BigInteger, nullable=False),
    Column("last_event_id", BigInteger, nullable=False, server_default="0"),
    Column("last_ping_event_id", BigInteger, nullable=False, server_default="0"),
    key=("board_id", "task_id", "platform", "chat_id", "thread_id"),
    constraints=(scoped_fk(("board_id",), "kanban_boards", ("board_id",), ondelete="CASCADE"),))
