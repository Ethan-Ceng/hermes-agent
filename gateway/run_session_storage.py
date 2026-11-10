"""Scoped async session resources borrowed by the gateway runner."""

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("gateway.run")


def close_gateway_session_resources():
    from gateway.delivery_backend import close_delivery_handles
    from hermes_cli.db_sessions import close_session_resources
    close_delivery_handles()
    return close_session_resources()


class GatewaySessionStorageMixin:
    def _open_session_db_for_active_scope(self, raise_on_error: bool = False) -> Any:
        """AsyncSessionDB for the active profile scope, resolved per access (not in ``__init__``) since
        ``SessionDB()`` reads the context-local HERMES_HOME; one handle cached per path. Construction
        failure enters bounded backoff; ``raise_on_error=True`` (priming) propagates it.

        Same per-path cache as ``SessionStore._open_session_db_for_active_scope`` (#88532): ``SessionDB()``
        resolves ``_default_db_path()`` at call time through the context-local HERMES_HOME override
        installed by ``_profile_runtime_scope``, so resolving per access — instead of once in ``__init__`` —
        is what lets /resume, /title, /history and session search on a multiplexed gateway read the *serving
        profile's* store rather than the root one.
        One ``AsyncSessionDB`` is cached per resolved path, so the wrapper identity is stable per profile
        (callers compare and stash it) and two profiles never share a handle. A construction failure enters
        bounded backoff; one caller retries after the deadline while concurrent callers continue to see the
        unavailable fallback. ``raise_on_error=True`` (construction-time priming) propagates the failure
        after recording that recoverable state so ``__init__`` can record ``_session_db_init_error`` for the
        #88235 broadcast.
        """
        from hermes_state import AsyncSessionDB, _default_db_path
        from hermes_cli.db_sessions import acquire_sessions as acquire
        from hermes_cli.db_setup import storage_backend
        from hermes_db.errors import StorageUnavailableError
        from gateway.session_db_recovery import RecoverableHandleCache
        path = Path(_default_db_path())
        native = storage_backend(path.resolve().parent) == "postgresql"
        cache = getattr(self, "_session_db_handle_cache", None)
        if cache is None:
            # Test runners built with object.__new__ skip __init__.
            cache = RecoverableHandleCache(
                handles=self._session_db_handles, lock=self._session_db_handles_lock)
            self._session_db_handle_cache = cache

        def _open():
            # Borrow the SessionStore's handle (same path) so state.db doesn't get two writers/pools.
            # The store owns/sweeps it at shutdown; this cache holds only the async wrapper (close_all).
            # Both caches resolve the SAME ``_default_db_path()``, so the process was holding two writer
            # connections and two read pools against one state.db — the fd budget doubled for nothing, and
            # doubled again per profile on a multiplexed gateway (#98573). A borrowed wrapper goes stale only
            # when the registry tears its generation down (profile unserve/delete); both caches then drop
            # the dead handle and reopen through the registry. While the store's own open is failing there
            # is nothing to borrow, so nothing is cached here either.
            store = getattr(self, "session_store", None)
            borrowed = getattr(store, "_db", None) if store is not None else None
            if borrowed is not None:
                wrapper = AsyncSessionDB(borrowed)
                # close_all_session_db_handles() must not close what the store owns (its sweep runs first).
                wrapper.__dict__["_hermes_borrowed_handle"] = True
                return wrapper
            if store is not None:
                # Store handle unavailable: opening our own would resurrect the duplicate borrowed away.
                if native:
                    raise StorageUnavailableError("SessionStore handle unavailable")
                raise RuntimeError("SessionStore SQLite handle unavailable")
            try:
                return AsyncSessionDB(acquire())
            except Exception as exc:
                logger.warning("SQLite session store not available: %s", exc)
                raise

        def _recovered() -> None:
            self._session_db_init_error = None
            logger.info("SQLite session store recovered")

        handle = cache.get(path, _open, raise_on_error=raise_on_error or native, on_recovered=_recovered)
        if native and handle is None:
            raise StorageUnavailableError("Session storage is unavailable; retry after recovery")
        return handle


    def close_all_session_db_handles(self) -> None:
        """Close every per-profile AsyncSessionDB this runner opened.

        Drained under the lock, closed outside it; a pinned handle is the pinner's to close. Wrappers
        BORROWED from ``session_store`` are skipped: the store's sweep (runs first) closes them.

        See #98573.
        """
        def _close(db) -> None:
            if getattr(db, "__dict__", {}).get("_hermes_borrowed_handle"):
                return
            inner = getattr(db, "_db", db)
            if inner is None or not hasattr(inner, "close"):
                return
            # Shared instances no-op on close() (the registry owns the lifecycle). Release the refcount
            # instead (#90837).
            from hermes_db.access import release_session_store as release_or_close
            try:
                release_or_close(inner)
            except Exception as exc:
                logger.debug("SessionDB close error during handle sweep: %s", exc, exc_info=True)

        self._session_db_handle_cache.close_all(_close)
