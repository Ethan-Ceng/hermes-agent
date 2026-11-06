"""Frozen search projections for new PG stores; does not read SQLite formats."""

import re

from alembic import op
from sqlalchemy import text

revision = "0002_search_projection"
down_revision = "0001_session_storage"
branch_labels = None
depends_on = None

# The trigger covers INSERT SELECT compression clones as well as ordinary
# writers. All function/object references are namespace-qualified; invocation
# does not inherit a mutable application search_path.
CHUNKS = """
CREATE TABLE {schema}.message_search_chunks (
 store_id TEXT NOT NULL, message_id BIGINT NOT NULL, chunk BIGINT NOT NULL,
 search_vector TSVECTOR NOT NULL,
 CONSTRAINT pk_message_search_chunks PRIMARY KEY (store_id,message_id,chunk),
 CONSTRAINT fk_message_search_chunks_message_id_messages FOREIGN KEY (store_id,message_id)
  REFERENCES {schema}.messages (store_id,id) ON DELETE CASCADE)
"""
TRIGGER = """
CREATE FUNCTION {schema}.sync_message_search() RETURNS trigger
 LANGUAGE plpgsql SET search_path=pg_catalog AS $hermes$
DECLARE
 first_char integer := 1; last_char integer; boundary integer;
 ordinal bigint := 0; document_length integer;
BEGIN
 IF TG_OP = 'UPDATE' THEN
  IF NEW.search_document IS NOT DISTINCT FROM OLD.search_document THEN
   RETURN NEW;
  END IF;
 END IF;
 DELETE FROM {schema}.message_search_chunks WHERE store_id=NEW.store_id AND message_id=NEW.id;
 document_length := char_length(NEW.search_document);
 WHILE first_char <= document_length LOOP
  last_char := least(document_length, first_char + 8191);
  IF last_char < document_length THEN
   boundary := regexp_instr(NEW.search_document, '[^[:alnum:]_]', last_char);
   last_char := CASE WHEN boundary > 0 THEN boundary ELSE document_length END;
  END IF;
  INSERT INTO {schema}.message_search_chunks(store_id,message_id,chunk,search_vector)
   VALUES (NEW.store_id,NEW.id,ordinal,
    to_tsvector('pg_catalog.simple'::regconfig,substring(NEW.search_document FROM first_char FOR last_char-first_char+1)));
  EXIT WHEN last_char >= document_length;
  boundary := regexp_instr(NEW.search_document, '[^[:alnum:]_]', greatest(first_char+1,last_char-2048));
  first_char := CASE WHEN boundary > 0 AND boundary < last_char THEN boundary+1 ELSE last_char+1 END;
  ordinal := ordinal+1;
 END LOOP;
 RETURN NEW;
END;
$hermes$
"""


def _backfill(connection, table):
    cursor = ("", -1)
    query = text(f"SELECT store_id,id,role,search_content,tool_name,tool_calls FROM {table} "
        "WHERE (store_id,id) > (:store,:id) ORDER BY store_id,id LIMIT 100")
    update = text(f"UPDATE {table} SET search_document=:document,search_grams=:grams WHERE store_id=:store AND id=:id")
    while rows := connection.execute(query, {"store": cursor[0], "id": cursor[1]}).mappings().all():
        changes = []
        for row in rows:
            content = row["search_content"] or ""
            if row["role"] == "tool":
                content = content[:8192]
            document = "\n".join(str(value) for value in (content, row["tool_name"], row["tool_calls"]) if value)
            grams = set()
            for word in re.findall(r"[^\W_]+", document.casefold()):
                grams.update(word)
                grams.update(word[index:index + 2] for index in range(len(word) - 1))
            changes.append({"store": row["store_id"], "id": row["id"], "document": document, "grams": sorted(grams)})
        connection.execute(update, changes)
        cursor = rows[-1]["store_id"], rows[-1]["id"]


def upgrade():
    from hermes_db.errors import StorageSchemaError

    connection = op.get_bind()
    quote = connection.dialect.identifier_preparer.quote
    table = quote(op.get_context().config.attributes["schema"]) + ".messages"
    extension_schema = connection.scalar(text("SELECT n.nspname FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace WHERE e.extname='pg_trgm'"))
    if extension_schema is None:
        raise StorageSchemaError("PostgreSQL pg_trgm is required; ask the database administrator to prepare it before upgrading")
    connection.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN search_document TEXT, ADD COLUMN search_grams TEXT[]")
    schema = quote(op.get_context().config.attributes["schema"])
    connection.exec_driver_sql(CHUNKS.format(schema=schema))
    connection.exec_driver_sql(TRIGGER.format(schema=schema))
    connection.exec_driver_sql(f"CREATE TRIGGER sync_message_search AFTER INSERT OR UPDATE OF search_document ON {table} "
        f"FOR EACH ROW EXECUTE FUNCTION {schema}.sync_message_search()")
    _backfill(connection, table)
    connection.exec_driver_sql(f"CREATE INDEX ix_message_search_chunks_fts ON {schema}.message_search_chunks USING gin (search_vector)")
    connection.exec_driver_sql(f"CREATE INDEX ix_messages_search_trgm ON {table} USING gin (search_document {quote(extension_schema)}.gin_trgm_ops)")
    connection.exec_driver_sql(f"CREATE INDEX ix_messages_search_grams ON {table} USING gin (search_grams)")


def downgrade():
    raise RuntimeError("Session storage downgrade is unsupported; use an administrator-managed database backup")
