"""Owned dataset identity and closed domain reads for an authenticated adopted worker."""

import asyncio

from hermes_state_runtime import RuntimeStoreError


def storage_identity(db):
    from hermes_db.health import is_postgresql_store, profile_home_for_store
    pg = is_postgresql_store(db)
    if pg:
        from hermes_db.core.values import resource_key
    return {'version': 1, 'backend': 'postgresql' if pg else 'sqlite',
            'profile_home': str(profile_home_for_store(db)),
            'store_id': db.scope.require_store_id() if pg else None,
            'target': resource_key(db._transactions) if pg else None}


async def worker_domain_read(connection, ref, params):
    payload = params['payload']
    if (set(payload) != {'name', 'arguments'} or not isinstance(payload['name'], str)
            or not isinstance(payload['arguments'], dict)):
        raise RuntimeStoreError('invalid_params')
    return await asyncio.to_thread(_read, connection, ref, params)


def _read(connection, ref, params):
    from gateway.session_worker_recall import verify_read
    from hermes_db.health import is_postgresql_store
    from hermes_db.domains.runtime.access import runtime_for_store
    verify_read(connection, ref, params)
    db = connection.authority.db
    if not is_postgresql_store(db):
        raise RuntimeStoreError('unsupported_domain')
    return runtime_for_store(db).read_domain(params['session_id'], **params['payload'])
