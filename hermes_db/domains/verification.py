"""Resolve the evidence owner's backend before touching any ledger file."""


def postgres_resource():
    from hermes_cli.db_setup import resolve_db_configuration
    from hermes_db.factory import acquire_domain

    settings, scope = resolve_db_configuration()
    if settings.backend == "sqlite":
        return None
    return acquire_domain("verification", settings, scope)
