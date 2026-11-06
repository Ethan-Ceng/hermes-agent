"""Current Core metadata. No connection or DDL runs at import time."""


def load_metadata():
    from importlib import import_module
    from hermes_db.tables.metadata import metadata

    for module in ("conversations", "runtime", "gateway", "api"):
        import_module(f"hermes_db.tables.{module}")
    return metadata
