"""Own the process-home PostgreSQL delivery handle across off-loop calls."""

import atexit
import os
from threading import RLock

_lock = RLock()
_ledgers = {}


def postgres_ledger():
    from hermes_constants import get_process_hermes_home
    from hermes_cli.db_setup import resolve_db_configuration

    settings, scope = resolve_db_configuration(get_process_hermes_home())
    if settings.backend == "sqlite":
        return None
    key = (os.getpid(), settings, scope)
    with _lock:
        if key not in _ledgers:
            from hermes_db.factory import acquire_db
            from hermes_db.domains.runtime.postgres.delivery_ledger import PostgresDeliveryLedger

            handle = acquire_db(settings, scope)
            try:
                ledger = PostgresDeliveryLedger(handle.sessions)
            except BaseException:
                handle.close()
                raise
            _ledgers[key] = handle, ledger
        return _ledgers[key][1]


def close_delivery_handles():
    with _lock:
        owned = [_ledgers.pop(key)[0] for key in list(_ledgers) if key[0] == os.getpid()]
    for handle in owned:
        handle.close()


atexit.register(close_delivery_handles)
