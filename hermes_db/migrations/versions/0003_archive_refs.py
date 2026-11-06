"""Frozen bounded spillover-name projections for current PG transcript rows."""

import re

from alembic import op
from sqlalchemy import text

revision = "0003_archive_refs"
down_revision = "0002_search_projection"
branch_labels = None
depends_on = None

_NAME = re.compile(r"spillover(?:/|\\+)([A-Za-z0-9_.-]+)")


def _backfill(connection, table):
    cursor = ("", -1)
    query = text(f"SELECT store_id,id,role,content,api_content FROM {table} WHERE (store_id,id) > (:store,:id) ORDER BY store_id,id LIMIT 100")
    update = text(f"UPDATE {table} SET spillover_names=:names,roster_preview=:preview WHERE store_id=:store AND id=:id")
    while rows := connection.execute(query, {"store": cursor[0], "id": cursor[1]}).mappings().all():
        changes = []
        for row in rows:
            names = set()
            for raw in (row["content"], row["api_content"]):
                if raw is not None:
                    names.update(_NAME.findall(bytes(raw).decode("utf-8", "replace")))
            preview = None
            if row["role"] in ("user", "assistant") and row["content"] is not None:
                raw = bytes(row["content"])
                value = raw[1:].decode("utf-8") if raw[:1] == b"T" else raw[1:]
                collapsed = " ".join(str(value or "").split()).strip()
                if collapsed:
                    preview = (collapsed[:80] + "..." if len(collapsed) > 80 else collapsed).encode("utf-8")
            changes.append({"store": row["store_id"], "id": row["id"], "names": sorted(names) or None, "preview": preview})
        connection.execute(update, changes)
        cursor = rows[-1]["store_id"], rows[-1]["id"]


def upgrade():
    connection = op.get_bind()
    quote = connection.dialect.identifier_preparer.quote
    table = quote(op.get_context().config.attributes["schema"]) + ".messages"
    connection.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN spillover_names TEXT[], ADD COLUMN roster_preview BYTEA")
    _backfill(connection, table)
    connection.exec_driver_sql(f"CREATE INDEX ix_messages_store_spillover_refs ON {table} (store_id,id) WHERE spillover_names IS NOT NULL")


def downgrade():
    raise RuntimeError("Session storage downgrade is unsupported; use an administrator-managed database backup")
