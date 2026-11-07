"""Project records, directories, metadata and discovery cache."""

from sqlalchemy import BigInteger, Column, Index, LargeBinary, Text, UniqueConstraint
from hermes_db.tables.metadata import scoped_fk, scoped_table

project_locks = scoped_table("project_locks", key=())
projects = scoped_table("projects", Column("id", LargeBinary, nullable=False), Column("slug", Text, nullable=False),
    Column("name", LargeBinary, nullable=False),
    *[Column(name, LargeBinary) for name in ("description", "icon", "color", "board_slug", "primary_path")],
    Column("created_at", BigInteger, nullable=False), Column("archived", BigInteger, nullable=False, server_default="0"),
    key=("id",), constraints=(UniqueConstraint("store_id", "slug"),))
project_folders = scoped_table("project_folders", Column("project_id", LargeBinary, nullable=False),
    Column("path", LargeBinary, nullable=False), Column("label", LargeBinary),
    Column("is_primary", BigInteger, nullable=False, server_default="0"), Column("added_at", BigInteger, nullable=False),
    key=("project_id", "path"), constraints=(scoped_fk(("project_id",), "projects", ("id",), ondelete="CASCADE"),))
project_meta = scoped_table("project_meta", Column("key", Text, nullable=False), Column("value", LargeBinary), key=("key",))
discovered_repos = scoped_table("discovered_repos", Column("root", LargeBinary, nullable=False),
    Column("label", LargeBinary), Column("last_seen", BigInteger, nullable=False), key=("root",))
Index("ix_projects_store_created", projects.c.store_id, projects.c.created_at)
Index("ix_project_folders_store_path", project_folders.c.store_id, project_folders.c.path)
