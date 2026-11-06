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

    def persist_delegation(self, *, owner, **kwargs):
        from hermes_db.operations.worker_delegations import handlers
        from hermes_state_runtime import RuntimeStoreError
        callbacks = handlers(owner)
        if kwargs["execution_id"] != owner.execution_id:
            raise RuntimeStoreError("permission_denied")
        return self.apply_worker_receipt(**kwargs, handlers=callbacks)
