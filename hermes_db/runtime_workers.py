"""Worker facade entry points share the profile-owned runtime transaction."""

from hermes_db.operations import workers


class RuntimeWorkers:
    def register_worker(self, **kwargs):
        with self._write() as conn:
            return workers.register(conn, self.scope, **kwargs)

    def adopt_worker(self, **kwargs):
        with self._write() as conn:
            return workers.adopt(conn, self.scope, **kwargs)

    def apply_worker_receipt(self, **kwargs):
        with self._write() as conn:
            return workers.apply_receipt(conn, self.scope, **kwargs)

    def mutate_worker(self, **kwargs):
        from hermes_db.operations.worker_handlers import handlers
        return self.apply_worker_receipt(**kwargs, handlers=handlers())

    def worker_claim_origin(self, params):
        from hermes_db.repositories.workers import claim_origin
        with self._store._read() as conn:
            return claim_origin(conn, self.scope, params)

    def worker_retry_target(self, params):
        from hermes_db.repositories.workers import retry_target
        with self._store._read() as conn:
            return retry_target(conn, self.scope, params)

    def persist_delegation(self, *, owner, **kwargs):
        from hermes_db.operations.worker_delegations import handlers
        from hermes_state_runtime import RuntimeStoreError
        callbacks = handlers(owner)
        if kwargs["execution_id"] != owner.execution_id:
            raise RuntimeStoreError("permission_denied")
        return self.apply_worker_receipt(**kwargs, handlers=callbacks)
