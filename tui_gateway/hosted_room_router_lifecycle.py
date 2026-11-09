"""Threaded room-router lifecycle over explicit backend claim/release methods."""
from __future__ import annotations
import logging
from collections.abc import Callable
from agent.memory_provider import spawn_context_thread
logger = logging.getLogger("tui_gateway.hosted_room_router_call")
CLAIM_TTL_SECONDS = 120.0

class RouterCallLifecycle:

    def start(self, key: tuple[str, str], call: Callable[[], tuple[str, ...] | None],
              record: Callable[[tuple[str, ...] | None], None]) -> bool:
        with self._lock:
            if key in self._inflight:
                return False
            self._inflight.add(key)
        try:
            claimed = self._claim(key)
        except BaseException:
            with self._lock:
                self._inflight.discard(key)
            raise
        if not claimed:
            with self._lock:
                self._inflight.discard(key)
            return False

        def run() -> None:
            try:
                record(call())
            except Exception:  # health: allow BLE001 -- a lost answer is re-asked on the next preparation
                logger.warning("hosted room %s: recording the router answer failed", key[0], exc_info=True)
            finally:
                try:
                    self._release(key)
                except Exception:  # health: allow BLE001 -- an unreleased claim only expires (CLAIM_TTL_SECONDS)
                    logger.warning("hosted room %s: releasing the router claim failed", key[0], exc_info=True)
                with self._lock:
                    self._inflight.discard(key)
        # The owner's profile scope is bound explicitly inside ask_router (_profile_runtime_scope).
        spawn_context_thread(run, name=f"hosted-room-router-{key[0][:16]}").start()
        return True

    def inflight(self, key: tuple[str, str]) -> bool:
        with self._lock:
            return key in self._inflight
