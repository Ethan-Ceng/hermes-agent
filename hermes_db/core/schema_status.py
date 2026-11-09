"""Read-only per-domain support and table checks for explicit schema management."""

from hermes_db.core.catalog import KNOWN_DOMAINS, POSTGRES_DOMAINS, required_tables


def domain_status_on_connection(conn, schema, *, revision_ready, extensions_ready):
    from sqlalchemy import text

    actual = set(conn.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema=:schema"),
                              {"schema": schema}).scalars())
    result = {}
    for name in KNOWN_DOMAINS:
        spec = POSTGRES_DOMAINS.get(name)
        missing = sorted(required_tables(spec) - actual) if spec else []
        result[name] = {"supported": spec is not None, "required_revision": spec.revision if spec else None,
                        "missing_tables": missing,
                        "ready": spec is not None and revision_ready and extensions_ready and not missing}
    return result
