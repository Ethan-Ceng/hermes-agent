"""Shared-schema table declarations; every key and reference is store-scoped."""

from sqlalchemy import BigInteger, Column, ForeignKeyConstraint, MetaData, PrimaryKeyConstraint, Table, Text

SCHEMA = "hermes_session"
metadata = MetaData(schema=SCHEMA, naming_convention={
    "pk": "pk_%(table_name)s", "fk": "fk_%(table_name)s_%(column_1_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_1_name)s", "ix": "ix_%(table_name)s_%(column_1_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
})


def scoped_table(name, *columns, key, constraints=()):
    return Table(name, metadata, Column("store_id", Text, nullable=False), *columns,
                 PrimaryKeyConstraint("store_id", *key), *constraints)


def scoped_fk(local, target, remote, *, ondelete=None):
    return ForeignKeyConstraint(["store_id", *local],
        [f"{SCHEMA}.{target}.{name}" for name in ("store_id", *remote)], ondelete=ondelete)


def text_columns(*names, nullable=True):
    return [Column(name, Text, nullable=nullable) for name in names]


def zero_columns(*names, nullable=False):
    return [Column(name, BigInteger, nullable=nullable, server_default="0") for name in names]
