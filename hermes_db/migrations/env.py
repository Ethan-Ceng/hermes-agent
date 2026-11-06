"""Alembic runs only through an explicit operation on an injected Connection."""

from alembic import context

from hermes_db.errors import StorageSchemaError


def run_migrations():
    config = context.config
    connection = config.attributes.get("connection")
    schema = config.attributes.get("schema")
    if connection is None or schema is None:
        raise StorageSchemaError("Use hermes db upgrade with explicit profile storage settings")
    context.configure(connection=connection, version_table_schema=schema,
                      transactional_ddl=True, include_schemas=True)
    with context.begin_transaction():
        context.run_migrations()


run_migrations()
