"""Frozen first-class Projects schema; no SQLite data import."""

from alembic import op

revision = "0006_projects"
down_revision = "0005_verification"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    schema = conn.dialect.identifier_preparer.quote(op.get_context().config.attributes["schema"])
    conn.exec_driver_sql(f"CREATE TABLE {schema}.project_locks (store_id TEXT PRIMARY KEY)")
    conn.exec_driver_sql(f"""CREATE TABLE {schema}.projects (
        store_id TEXT NOT NULL, id BYTEA NOT NULL, slug TEXT NOT NULL, name BYTEA NOT NULL,
        description BYTEA, icon BYTEA, color BYTEA, board_slug BYTEA, primary_path BYTEA,
        created_at BIGINT NOT NULL, archived BIGINT NOT NULL DEFAULT 0,
        CONSTRAINT pk_projects PRIMARY KEY (store_id,id), CONSTRAINT uq_projects_store_id UNIQUE (store_id,slug))""")
    conn.exec_driver_sql(f"""CREATE TABLE {schema}.project_folders (
        store_id TEXT NOT NULL, project_id BYTEA NOT NULL, path BYTEA NOT NULL, label BYTEA,
        is_primary BIGINT NOT NULL DEFAULT 0, added_at BIGINT NOT NULL,
        CONSTRAINT pk_project_folders PRIMARY KEY (store_id,project_id,path),
        CONSTRAINT fk_project_folders_project_id_projects FOREIGN KEY (store_id,project_id)
        REFERENCES {schema}.projects (store_id,id) ON DELETE CASCADE)""")
    conn.exec_driver_sql(f"CREATE TABLE {schema}.project_meta (store_id TEXT NOT NULL, key TEXT NOT NULL, value BYTEA, "
                         "CONSTRAINT pk_project_meta PRIMARY KEY (store_id,key))")
    conn.exec_driver_sql(f"CREATE TABLE {schema}.discovered_repos (store_id TEXT NOT NULL, root BYTEA NOT NULL, label BYTEA, "
                         "last_seen BIGINT NOT NULL, CONSTRAINT pk_discovered_repos PRIMARY KEY (store_id,root))")
    conn.exec_driver_sql(f"CREATE INDEX ix_projects_store_created ON {schema}.projects (store_id,created_at)")
    conn.exec_driver_sql(f"CREATE INDEX ix_project_folders_store_path ON {schema}.project_folders (store_id,path)")


def downgrade():
    raise RuntimeError("Storage downgrade is unsupported; use an administrator-managed database backup")
