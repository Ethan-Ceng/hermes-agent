"""Bind Matrix encryption to its owning Profile; PG never invokes SDK SQLite migrations."""

import logging

from hermes_constants import get_hermes_home
from hermes_db.errors import StorageConfigurationError

logger = logging.getLogger(__name__)


def capture_storage(adapter):
    from plugins.plugin_storage import storage_profile
    home, backend = storage_profile(get_hermes_home())
    adapter._storage_home = home
    adapter._storage_backend = backend
    return backend


def make_client(client_class, adapter, **arguments):
    if adapter._storage_backend == "postgresql":
        from plugins.platforms.matrix.adapter_pg_client import PostgresMatrixClient
        return PostgresMatrixClient(profile_home=adapter._storage_home, **arguments)
    return client_class(**arguments)


def pg_dependencies_available():
    from plugins.plugin_storage import matrix_dependencies_available
    return matrix_dependencies_available()


def ensure_pg_dependencies(importer, namespace):
    from pm import extras
    required = set(extras.missing("matrix")) - {"asyncpg", "aiosqlite"}
    if required and not extras.ensure_and_bind("matrix", importer, namespace):
        return False
    try:
        namespace.update(importer())
    except ImportError:
        return False
    # E2EE's native libolm check belongs to encrypted connect; explicit plaintext still works.
    ready = extras.available("postgresql")
    if not ready:
        logger.warning("Matrix: PG encryption requires the project PM matrix and postgresql feature groups")
    return ready


class _StoreLifecycle:
    def __init__(self, store):
        self.store = store

    async def stop(self):
        await self.store.close()


async def _verify_identity(adapter, client, store, *, published=False):
    if not client.device_id or adapter._device_id_unverified:
        raise StorageConfigurationError("PG Matrix encryption requires a verified Matrix device identity")
    server = await adapter._query_own_device_keys(client)
    local = await store.get_account()
    server_keys = {str(key).split(":", 1)[0]: str(value) for key, value in (getattr(server, "keys", {}) or {}).items()}
    if (published and not server) or (server and (local is None or any(server_keys.get(name) != local.identity_keys[name] for name in ("ed25519", "curve25519")))):
        raise StorageConfigurationError(
            "Matrix device identity does not match this PG dataset; configure a fresh Matrix device and access token. "
            "Existing remote devices and SQLite crypto data were preserved")
    return bool(server)


async def connect_postgresql(adapter, client, api, state_store):
    from plugins.plugin_storage import plugin_profile_scope as _owning_profile
    from plugins.plugin_storage import matrix_crypto_store
    from mautrix.crypto import OlmMachine
    from mautrix.types import TrustState
    from plugins.platforms.matrix.adapter_crypto import _CryptoStateStore
    handle = None
    try:
        with _owning_profile(adapter._storage_home):
            store = matrix_crypto_store(account_id=str(client.mxid), device_id=str(client.device_id or ""),
                homeserver=adapter._homeserver, pickle_key=f"{client.mxid}:{client.device_id}", profile_home=adapter._storage_home)
            handle = _StoreLifecycle(store)
            await store.open()
            published = await _verify_identity(adapter, client, store)
            await store.put_device_id(client.device_id)
            olm = OlmMachine(client, store, _CryptoStateStore(state_store, adapter._joined_rooms, client))
            olm.share_keys_min_trust = TrustState.UNVERIFIED
            olm.send_keys_min_trust = TrustState.UNVERIFIED
            await olm.load()
            if not published:
                olm.account.shared = False
            await olm.share_keys()
            # The PG branch never deletes or resets a remote device on identity mismatch.
            await _verify_identity(adapter, client, store, published=True)
            await adapter._verify_or_bootstrap_cross_signing(olm, client)
            client.sync_store = store
            client.crypto = olm
            adapter._crypto_db = handle
        logger.info("Matrix: E2EE enabled with Profile PostgreSQL storage")
        return True
    except Exception as error:  # health: allow BLE001 -- SDK startup boundary closes resources; tracebacks can expose encryption keys
        # Optional E2EE never turns a failed selected database into successful plaintext startup.
        from hermes_db.errors import StorageError
        reason = str(error) if isinstance(error, StorageError) else type(error).__name__
        logger.error("Matrix: PG encryption setup failed: %s", reason)
        return await adapter._abort_connect(api, handle)


async def connect_selected(adapter, client, api, state_store):
    backend = getattr(adapter, "_storage_backend", None) or capture_storage(adapter)
    if backend == "postgresql":
        if not pg_dependencies_available():
            logger.error("Matrix: PG E2EE requires the project PM matrix and postgresql feature groups")
            return await adapter._abort_connect(api)
        return await connect_postgresql(adapter, client, api, state_store)
    from plugins.platforms.matrix.adapter_crypto_sqlite import connect_sqlite
    return await connect_sqlite(adapter, client, api, state_store)


def storage_diagnostics(adapter):
    backend = getattr(adapter, "_storage_backend", None) or capture_storage(adapter)
    if backend == "postgresql":
        return {"backend": backend, "deps_available": pg_dependencies_available(), "crypto_store_path": None}
    from plugins.platforms.matrix.adapter import _check_e2ee_deps
    return {"backend": backend, "deps_available": _check_e2ee_deps(), "crypto_store_path": str(adapter._crypto_db_path)}
