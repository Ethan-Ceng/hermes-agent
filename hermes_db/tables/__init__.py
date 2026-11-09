"""Current Core metadata. No connection or DDL runs at import time."""


def load_metadata():
    from importlib import import_module
    from hermes_db.core.catalog import POSTGRES_DOMAINS
    from hermes_db.tables.metadata import metadata

    for module in dict.fromkeys(module for spec in POSTGRES_DOMAINS.values() for module in spec.table_modules):
        import_module(f"hermes_db.tables.{module}")
    return metadata
