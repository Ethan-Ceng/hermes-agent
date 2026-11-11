"""RetainDB PG worker: durable rows own work; Events only wake a bounded claimant."""

import hashlib
import json
import logging
import threading
import uuid
from websockets.exceptions import WebSocketException
from plugins.plugin_storage import spawn_plugin_thread as spawn_context_thread
from plugins.plugin_storage import WorkerPersistenceError
from plugins.plugin_storage import redact_storage_error
from plugins.plugin_storage import plugin_profile_scope as _owning_profile
from plugins.plugin_storage import capture_queue
from plugins.plugin_storage import StorageConfigurationError, StorageError, UnknownCommitError
from plugins import plugin_storage as operations

logger = logging.getLogger(__name__)


class PostgresWriteQueue:
    def __init__(self, client, db_path, *, profile_home=None):
        destination = hashlib.sha256(json.dumps([client.base_url, client.project], ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()
        self.reference = capture_queue(profile_home, destination)
        self._client = client
        self._wake, self._stop = threading.Event(), threading.Event()
        self._shutdown_lock, self._shutdown = threading.Lock(), False
        counts = operations.retain_counts(self.reference)
        if counts["other_destination"]:
            logger.warning("RetainDB retains pending requests for another endpoint/project; restore that destination to deliver them")
        with _owning_profile(self.reference.profile_home):
            self._thread = spawn_context_thread(self._loop, name="retaindb-pg-writer")
        self._thread.start()
        self._wake.set()

    def _get_conn(self):
        raise StorageConfigurationError("PG RetainDB exposes named queue operations, not SQLite connections")

    def _execute(self, sql, params=()):
        raise StorageConfigurationError("PG RetainDB exposes named queue operations, not a SQLite SQL executor")

    def enqueue(self, user_id, session_id, messages):
        with self._shutdown_lock:
            if self._shutdown:
                return
            request_id = str(uuid.uuid4())
            record = operations.retain_prepare(self.reference, request_id, user_id, session_id, messages)
            try:
                operations.retain_enqueue(self.reference, record)
            except (UnknownCommitError, WorkerPersistenceError, OSError, WebSocketException) as error:
                error.request_id = request_id
                raise
            finally:
                self._wake.set()

    def _send(self, row):
        request_id, token = row["request_id"], row["claim_token"]
        if not operations.retain_renew(self.reference, request_id, token):
            return
        # A replayed renewal receipt is historical; only a fresh PG read admits this HTTP attempt.
        if not operations.retain_owns_claim(self.reference, request_id, token):
            return
        try:
            self._client.ingest_session(row["user_id"], row["session_id"], json.loads(row["messages_json"]))
        except (RuntimeError, OSError, ValueError) as error:
            safe = redact_storage_error(str(error))
            logger.warning("RetainDB ingest failed; pending row retained: %s", safe)
            operations.retain_fail(self.reference, request_id, token, safe)
        else:
            operations.retain_acknowledge(self.reference, request_id, token)

    def _wait(self):
        self._wake.wait(timeout=2)
        self._wake.clear()

    def _loop(self):
        while True:
            try:
                row = operations.retain_claim(self.reference)
                if row is not None:
                    self._send(row)
                    continue
            except StorageError:
                logger.exception("RetainDB queue operation failed; durable state requires reconciliation")
            except (WorkerPersistenceError, OSError, WebSocketException):
                logger.warning('RetainDB owner channel is unavailable; durable queue awaits receipt reconciliation')
            if self._stop.is_set():
                return
            self._wait()

    def shutdown(self):
        with self._shutdown_lock:
            self._shutdown = True
            self._stop.set()
            self._wake.set()
        self._thread.join(timeout=10)
        if self._thread.is_alive():
            logger.warning("RetainDB writer is still completing a request; unconfirmed work remains durable")
        else:
            try:
                counts = operations.retain_counts(self.reference)
            except (StorageError, WorkerPersistenceError, OSError, WebSocketException):
                logger.exception("RetainDB closed without proving its pending count")
            else:
                if counts["pending"]:
                    logger.info("RetainDB closed with %d pending requests retained for replay", counts["pending"])
