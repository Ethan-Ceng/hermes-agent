"""Scoped per-job locks and exact UTF-8 notepad entries."""

from sqlalchemy import Column, LargeBinary, Text
from hermes_db.tables.metadata import scoped_table

cron_notepad_locks = scoped_table("cron_notepad_locks", Column("job_id", LargeBinary, nullable=False), key=("job_id",))
cron_notepad = scoped_table("cron_notepad", Column("job_id", LargeBinary, nullable=False),
    Column("key", LargeBinary, nullable=False), Column("value", LargeBinary, nullable=False),
    Column("updated_at", Text, nullable=False), key=("job_id", "key"))
