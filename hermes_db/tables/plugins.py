"""Stable plugin namespace generations and lossless JSON values."""

from sqlalchemy import BigInteger, Column, Float, Index, LargeBinary, Text
from hermes_db.tables.metadata import scoped_table, scoped_fk

namespaces = scoped_table("plugin_namespaces", Column("plugin_id", Text, nullable=False), Column("namespace", Text, nullable=False),
    Column("revision", BigInteger, nullable=False, server_default="0"), key=("plugin_id", "namespace"))
records = scoped_table("plugin_records", Column("plugin_id", Text, nullable=False), Column("namespace", Text, nullable=False),
    Column("key", LargeBinary, nullable=False), Column("value", LargeBinary, nullable=False), Column("revision", BigInteger, nullable=False),
    Column("expires_at", Float), key=("plugin_id", "namespace", "key"),
    constraints=(scoped_fk(("plugin_id", "namespace"), "plugin_namespaces", ("plugin_id", "namespace"), ondelete="RESTRICT"),))
Index("idx_plugin_records_expiry", records.c.store_id, records.c.plugin_id, records.c.namespace, records.c.expires_at)
