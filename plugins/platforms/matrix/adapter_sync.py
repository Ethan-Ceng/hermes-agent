"""Dispatch sync before advancing a durable PG cursor; native SQLite keeps its existing behavior."""

import asyncio
import inspect
import logging
import time
from hermes_db.errors import StorageError

logger = logging.getLogger("plugins.platforms.matrix.adapter")


async def initial_sync(adapter, client):
    try:
        arguments = dict(timeout=10000, full_state=True)
        if getattr(adapter, "_storage_backend", None) == "postgresql":
            arguments["since"] = await client.sync_store.get_next_batch()
        sync_data = await client.sync(**arguments)
        if isinstance(sync_data, dict):
            adapter._joined_rooms.clear()
            await adapter._absorb_sync(client, sync_data, initial=True)
        else:
            logger.warning("Matrix: initial sync returned unexpected type %s", type(sync_data).__name__)
    except StorageError as error:
        logger.error("Matrix: initial sync storage failed: %s", error)
        return False
    except Exception as error:
        logger.exception("Matrix: initial sync error: %s", error)
    return True


async def absorb_sync(adapter, client, sync_data, *, initial=False):
    adapter._last_sync_ts = time.time()
    rooms_join = sync_data.get("rooms", {}).get("join", {})
    if rooms_join or initial:
        adapter._joined_rooms.update(rooms_join.keys())
        adapter._invalidate_room_identities()
    adapter._warn_encrypted_drops(rooms_join, client)
    token = sync_data.get("next_batch")
    persistent = getattr(adapter, "_storage_backend", None) == "postgresql"
    if token and not persistent:
        await client.sync_store.put_next_batch(token)
    if initial:
        logger.info("Matrix: initial sync complete, joined %d rooms", len(adapter._joined_rooms))
        await adapter._refresh_dm_cache()
    try:
        await adapter._dispatch_sync(sync_data)
    except StorageError:
        raise
    except Exception as error:
        logger.exception("Matrix: %s: %s", "initial sync event dispatch error" if initial else "sync event dispatch error", error)
    adapter._schedule_pending_invite_joins(sync_data)
    if token and persistent:
        await client.sync_store.put_next_batch(token)
    return token


async def dispatch_sync(adapter, sync_data):
    client = adapter._client
    if not client or not hasattr(client, "handle_sync"):
        return
    tasks = client.handle_sync(sync_data)
    if inspect.isawaitable(tasks):
        tasks = await tasks
    if tasks:
        results = await asyncio.gather(*tasks, return_exceptions=True)
        failed_storage = next((result for result in results if isinstance(result, StorageError)), None)
        for result in results:
            if isinstance(result, BaseException):
                logger.warning("Matrix: event handler failed during sync dispatch: %s", result)
        if any(isinstance(result, asyncio.CancelledError) for result in results):
            raise asyncio.CancelledError
        if failed_storage is not None:
            raise failed_storage
