"""Adapter-owned Responses resources, selected by the server-routed profile home."""

import threading
from contextlib import nullcontext

from hermes_db.errors import StorageClosedError


def initialize_response_state(adapter, sqlite_factory):
    from hermes_constants import get_hermes_home
    from hermes_db.integration.api_resources import open_response_store
    home = get_hermes_home()
    adapter._response_store = open_response_store(home, sqlite_factory, launch=True)
    adapter._response_store_home = str(home)
    adapter._response_stores = {}
    adapter._response_store_lock = threading.Lock()
    adapter._response_store_closed = False
    adapter._sqlite_response_store_factory = sqlite_factory


def current_response_store(adapter):
    from hermes_constants import get_hermes_home
    from hermes_db.integration.api_resources import open_response_store
    home = get_hermes_home()
    with adapter._response_store_lock:
        if getattr(adapter, "_response_store_closed", False):
            raise StorageClosedError("API response resources are closed")
        store = _cached_response(adapter, home)
        if _live_response(store):
            return store
    candidate = open_response_store(home, adapter._sqlite_response_store_factory)
    with adapter._response_store_lock:
        closed = adapter._response_store_closed
        previous = _cached_response(adapter, home)
        store = None if closed else previous
        if not closed and not _live_response(previous):
            store = candidate
            if str(home) == adapter._response_store_home:
                adapter._response_store = candidate
            else:
                adapter._response_stores[str(home)] = candidate
    if store is not candidate:
        candidate.close()
    if store is candidate and previous is not None:
        previous.close()
    if closed:
        raise StorageClosedError("API response resources are closed")
    return store


def _cached_response(adapter, home):
    return adapter._response_store if str(home) == adapter._response_store_home else adapter._response_stores.get(str(home))


def _live_response(store):
    from hermes_db.integration.api_resources import OwnedApiStore
    return store is not None and (not isinstance(store, OwnedApiStore) or store.is_open)


def drain_response_stores(adapter):
    lock = getattr(adapter, "_response_store_lock", None)
    with lock or nullcontext():
        if getattr(adapter, "_response_store_closed", False):
            return []
        adapter._response_store_closed = True
        routed = getattr(adapter, "_response_stores", {})
        stores = [s for s in (getattr(adapter, "_response_store", None), *routed.values()) if s is not None]
        routed.clear()
    return stores


def persist_run_status(adapter, run_id, status, *, scope=None):
    from hermes_db.health import is_postgresql_store
    from hermes_db.integration.run_resources import ProfileRunStores
    store = adapter._run_idempotency_store
    if isinstance(store, ProfileRunStores) or is_postgresql_store(store):
        return store.update_status(run_id, status, scope=scope or adapter._run_owners.get(run_id))
    return store.update_status(run_id, status)


def native_run_scope(adapter, scope):
    from hermes_db.health import is_postgresql_store
    from hermes_db.integration.run_resources import ProfileRunStores
    store = adapter._run_idempotency_store
    return store.is_native_scope(scope) if isinstance(store, ProfileRunStores) else is_postgresql_store(store)


def api_profile_namespace(adapter, legacy_name):
    from hermes_cli.db_setup import storage_backend
    if storage_backend() != "postgresql":
        return legacy_name
    store = adapter._current_response_store()
    return "pg-store:" + store.scope.require_store_id()


def chat_session_id(adapter, system_prompt, first_user, profile):
    from gateway.platforms.api_server import _derive_chat_session_id
    return _derive_chat_session_id(system_prompt, first_user, api_profile_namespace(adapter, profile))


async def chat_history(adapter, session_id, supplied_history):
    import asyncio
    import logging
    from hermes_db.errors import StorageError
    from gateway.platforms.api_server_runs import _resolve_live_session_id
    try:
        db = await adapter._ensure_session_db_async()
        if db is None:
            return session_id, supplied_history
        resolved = await _resolve_live_session_id(adapter, session_id)
        return resolved, await asyncio.to_thread(db.get_messages_as_conversation, resolved)
    except StorageError:
        raise
    except Exception as exc:  # health: allow BLE001 -- original SQLite request-history fallback; storage failures propagate above
        logging.getLogger(__name__).warning("Failed to load session history for %s: %s", session_id, exc)
        return session_id, []


async def call_with_storage_errors(handler, adapter, request, *args, **kwargs):
    from hermes_db.errors import StorageError, UnknownCommitError
    from gateway.platforms.api_server import _error_response
    try:
        return await handler(adapter, request, *args, **kwargs)
    except UnknownCommitError:
        response = _error_response("Session commit outcome is unknown; inspect the original request identity", 503,
            code="storage_unknown_commit")
        response.headers["x-should-retry"] = "false"
        return response
    except StorageError:
        return _error_response("Session storage unavailable", 503, code="storage_unavailable")
