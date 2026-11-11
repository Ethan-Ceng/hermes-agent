"""Original SDK SQLite startup and legacy migration, used only by SQLite Profiles."""

import logging
from typing import Any

logger = logging.getLogger("plugins.platforms.matrix.adapter")


async def connect_sqlite(self, client: Any, api: Any, state_store: Any) -> bool:
    """Set up the Olm machine + crypto store. Returns False when connect must abort."""
    from plugins.platforms.matrix.adapter import _check_e2ee_deps, _E2EE_INSTALL_HINT, TrustState
    if not _check_e2ee_deps():
        if self._e2ee_mode == "optional":
            logger.warning(
                "Matrix: E2EE optional but dependencies are missing. Continuing without "
                "encrypted-room support. %s", _E2EE_INSTALL_HINT)
            self._encryption = False
        else:
            logger.error(
                "Matrix: E2EE is required but dependencies are missing. %s. Refusing to connect — "
                "encrypted rooms would silently fail.", _E2EE_INSTALL_HINT)
            return await self._abort_connect(api)
    if not self._encryption:
        return True
    phase = "import"
    crypto_db = None
    try:
        from mautrix.crypto import OlmMachine
        from mautrix.crypto.store.asyncpg import PgCryptoStore
        from plugins.platforms.matrix.storage_schema import open_crypto_database
        phase = "create"
        crypto_db = await open_crypto_database(self._crypto_db_path)
        self._crypto_db = crypto_db
        if (self._store_dir / "crypto_store.pickle").exists():  # pre-SQLite era
            logger.info("Matrix: removing legacy crypto_store.pickle (migrated to SQLite)")
            (self._store_dir / "crypto_store.pickle").unlink()
        _acct_id = self._user_id or "hermes"
        # Key on the RESOLVED client.device_id (token's real device), not the configured
        # one, or the Olm account is stored under a key that can never be looked up.
        _pickle_key = f"{_acct_id}:{client.device_id or self._device_id or 'default'}"
        crypto_store = PgCryptoStore(account_id=_acct_id, pickle_key=_pickle_key, db=crypto_db)
        await crypto_store.open()
        _store_was_reset = False
        if client.device_id:
            _store_was_reset = await self._reset_crypto_store_if_device_changed(crypto_store, client.device_id)
            await crypto_store.put_device_id(client.device_id)
        # A just-deleted store has no account to migrate.
        if not _store_was_reset and not await self._migrate_legacy_crypto_pickle(
                crypto_store, crypto_db, _acct_id, _pickle_key):
            logger.warning("Matrix: crypto pickle migration failed — E2EE may not work correctly")
        from plugins.platforms.matrix.adapter_crypto import _CryptoStateStore
        crypto_state = _CryptoStateStore(state_store, self._joined_rooms, client)
        olm = OlmMachine(client, crypto_store, crypto_state)
        olm.share_keys_min_trust = TrustState.UNVERIFIED
        olm.send_keys_min_trust = TrustState.UNVERIFIED
        await olm.load()
        if not await self._verify_device_keys_on_server(client, olm):
            return await self._abort_connect(api, crypto_db)
        try:
            await olm.share_keys()
        except Exception as exc:
            logger.exception("Matrix: SQLite share_keys() warning during startup")
            if "already exists" in str(exc):
                logger.error(
                    "Matrix: device %s has stale one-time keys on the server signed with a "
                    "previous identity key. Delete the device from the homeserver and restart, "
                    "or generate a new access token to get a fresh device ID.", client.device_id)
                return await self._abort_connect(api, crypto_db)
        await self._verify_or_bootstrap_cross_signing(olm, client)
        client.crypto = olm
        logger.info(
            "Matrix: E2EE enabled (store: %s%s)", str(self._crypto_db_path),
            f", device_id={client.device_id}" if client.device_id else "")
    except Exception as exc:
        logger.exception("Matrix: SQLite encryption setup failed")
        if crypto_db is not None:
            await crypto_db.stop()
            self._crypto_db = None
        return await self._e2ee_setup_failed(phase, exc, api)
    return True
