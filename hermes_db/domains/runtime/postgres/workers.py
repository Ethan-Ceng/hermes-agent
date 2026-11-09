"""Explicit runtime workers component borrowing the owner context; no pools or session facade."""
from hermes_db.domains.runtime.postgres.operations import workers

class RuntimeWorkers:

    def __init__(self, context):
        self._context = context

    def read_domain(self, session_id, name, arguments):
        from hermes_db.domains.runtime.postgres.operations.worker_domains import read
        with self._context.read() as conn:
            return read(conn, self._context.scope, session_id, name, arguments)

    def worker_session(self, execution_id):
        from hermes_db.domains.runtime.postgres.queries.workers import execution
        with self._context.read() as conn:
            row = execution(conn, self._context.scope, execution_id)
            return row['session_id'] if row else None

    def reserve_admission_worker(self, **kwargs):
        from hermes_db.domains.runtime.postgres.operations.worker_reservation import reserve
        with self._context.write() as conn:
            return reserve(conn, self._context.scope, same_owner=self._context.session.ownership.same_owner, **kwargs)

    def lose_admission_worker(self, **kwargs):
        from hermes_db.domains.runtime.postgres.operations.worker_reservation import lose
        with self._context.write() as conn:
            return lose(conn, self._context.scope, **kwargs)

    def delegation_event(self, session_id, execution_id, delegation_id):
        import json
        from hermes_db.domains.runtime.postgres.queries.delegations import owned
        with self._context.read() as conn:
            row = owned(conn, self._context.scope, session_id, execution_id, delegation_id)
            return json.loads(row['event_json']) if row['delivery_state'] == 'pending' else None

    def register_worker(self, **kwargs):
        with self._context.write() as conn:
            return workers.register(conn, self._context.scope, **kwargs)

    def adopt_worker(self, **kwargs):
        with self._context.write() as conn:
            return workers.adopt(conn, self._context.scope, **kwargs)

    def apply_worker_receipt(self, **kwargs):
        with self._context.write() as conn:
            return workers.apply_receipt(conn, self._context.scope, **kwargs)

    def mutate_worker(self, **kwargs):
        handlers = self._context.worker_handlers(self._context.scope.profile_home, kwargs.get('operation'))
        return self.apply_worker_receipt(**kwargs, handlers=handlers)

    def worker_claim_origin(self, params):
        from hermes_db.domains.runtime.postgres.queries.workers import claim_origin
        with self._context.read() as conn:
            return claim_origin(conn, self._context.scope, params)

    def worker_retry_target(self, params):
        from hermes_db.domains.runtime.postgres.queries.workers import retry_target
        with self._context.read() as conn:
            return retry_target(conn, self._context.scope, params)

    def verify_worker_claim(self, params, claim, *, active_epoch=None):
        import hmac
        from hermes_db.domains.runtime.postgres.queries import runtime, workers as repo
        from hermes_db.domains.runtime.values import RuntimeStoreError, _secret_digest
        with self._context.read() as conn:
            target = repo.retry_target(conn, self._context.scope, params)
            row = repo.execution(conn, self._context.scope, params['execution_id'])
            if row is None:
                raise RuntimeStoreError('not_found')
            if row['session_id'] != target or not hmac.compare_digest(row['adoption_digest'], _secret_digest(claim)):
                raise RuntimeStoreError('permission_denied')
            if type(params['generation']) is not int or row['generation'] != params['generation']:
                raise RuntimeStoreError('stale_generation')
            if active_epoch is not None:
                runtime.require_epoch(conn, self._context.scope, active_epoch)
                if params['epoch'] != active_epoch or row['owner_epoch'] != active_epoch or row['status'] != 'running':
                    raise RuntimeStoreError('stale_generation')

    def persist_delegation(self, *, owner, **kwargs):
        from hermes_db.domains.runtime.postgres.operations.worker_delegations import handlers
        from hermes_db.domains.runtime.values import RuntimeStoreError
        callbacks = handlers(owner)
        if kwargs['execution_id'] != owner.execution_id:
            raise RuntimeStoreError('permission_denied')
        return self.apply_worker_receipt(**kwargs, handlers=callbacks)
