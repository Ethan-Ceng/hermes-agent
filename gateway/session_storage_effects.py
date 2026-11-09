"""Owner gates composed with explicitly scoped database effects."""

from hermes_db.health import is_postgresql_store


def admission_gate(authority, authorize=None, *, queue_only=False):
    if is_postgresql_store(authority.db):
        from hermes_db.domains.runtime.postgres.operations.effects import CoreEffect, invoke

        def native(conn, scope):
            authority._require_admission_open(queue_only=queue_only)
            invoke(authorize, conn, scope)

        return CoreEffect(native)

    def sqlite(conn):
        authority._require_admission_open(queue_only=queue_only)
        if authorize is not None:
            authorize(conn)

    return sqlite
