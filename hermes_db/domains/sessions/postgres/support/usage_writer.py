"""Owned deferred accounting queue. Only the worker executes its queued writes."""

from collections import deque
import logging
from threading import Condition
import time

from hermes_db.errors import StorageClosedError, StorageError, StorageWriteError, UnknownCommitError


class UsageWriter:
    def __init__(self, apply, profile):
        self._apply = apply
        self._profile = profile
        self._pending = deque()
        self._condition = Condition()
        self._thread = None
        self._busy = False
        self._stopped = False
        self._failure = None

    def enqueue(self, session_id, values):
        with self._condition:
            if self._stopped:
                raise StorageClosedError("Deferred accounting writer is closed")
            self._pending.append((session_id, dict(values)))
            if self._thread is None or not self._thread.is_alive():
                self._thread = self._new_thread()
                self._thread.start()
            self._condition.notify_all()

    def _new_thread(self):
        from agent.memory_provider import spawn_context_thread
        with self._profile.activate():
            return spawn_context_thread(self._run, name="postgres-token-writer")

    def _run(self):
        while True:
            with self._condition:
                if not self._pending and not self._stopped:
                    self._condition.wait(timeout=30)
                if not self._pending:
                    # Publish retirement while holding the enqueue lock.
                    self._thread = None
                    return
                session_id, values = self._pending.popleft()
                self._busy = True
            try:
                self._apply(session_id, **values)
            except StorageError as error:
                with self._condition:
                    self._failure = UnknownCommitError if isinstance(error, UnknownCommitError) else StorageWriteError
                logging.getLogger(__name__).warning("Deferred session accounting failed; no automatic replay was attempted")
            except Exception:
                with self._condition:
                    self._failure = StorageWriteError
                logging.getLogger(__name__).exception("Unexpected deferred session accounting failure")
            finally:
                with self._condition:
                    self._busy = False
                    self._condition.notify_all()

    def flush(self, timeout=5.0):
        deadline = time.monotonic() + max(0.0, timeout)
        with self._condition:
            while self._pending or self._busy:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(remaining)
            if self._failure is not None:
                raise self._failure("Deferred accounting failed; inspect the original operation before retrying")
            return True

    def close(self):
        with self._condition:
            self._stopped = True
            self._condition.notify_all()
            thread = self._thread
        if thread is not None:
            thread.join()
        self.flush()
