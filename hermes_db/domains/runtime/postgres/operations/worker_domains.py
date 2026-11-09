"""Closed domain effects on the canonical owner's existing Core receipt connection."""

from contextlib import contextmanager
from datetime import datetime, timedelta
from functools import partial

from hermes_state_runtime import RuntimeStoreError


class ReceiptDomainResource:
    def __init__(self, conn, scope, *, writable=False):
        self.conn, self.scope, self.writable = conn, scope, writable

    @contextmanager
    def read(self):
        yield self.conn

    @contextmanager
    def write(self):
        if not self.writable:
            raise RuntimeStoreError('permission_denied')
        yield self.conn


def fields(payload, required):
    if not isinstance(payload, dict) or set(payload) != set(required):
        raise RuntimeStoreError('invalid_params')


def owned_session(payload, session_id):
    if payload.get('session_id') != session_id:
        raise RuntimeStoreError('permission_denied')


def text(value):
    if not isinstance(value, str) or not value:
        raise RuntimeStoreError('invalid_params')


def verification(conn, scope, session_id, payload, *, operation):
    from hermes_db.domains.verification import postgres as operations
    resource = ReceiptDomainResource(conn, scope, writable=operation != 'status')
    if operation == 'record':
        return {'value': record_verification(resource, session_id, payload)}
    keys = {'session_id', 'root'} | ({'changed'} if operation == 'mark_edited' else set())
    fields(payload, keys)
    owned_session(payload, session_id)
    text(payload['root'])
    if operation == 'status':
        return {'value': operations.status(resource, session_id, payload['root'])}
    if not isinstance(payload['changed'], list) or any(not isinstance(value, str) for value in payload['changed']):
        raise RuntimeStoreError('invalid_params')
    from agent.verification_evidence import _utc_now
    return {'value': operations.mark_edited(resource, session_id, payload['root'], payload['changed'], _utc_now())}


def record_verification(resource, session_id, payload):
    from agent.verification_evidence import (
        VerificationEvidence, _utc_now, _MAX_EVIDENCE_AGE_DAYS,
        _MAX_EVENTS_PER_SESSION_ROOT, _MAX_TOTAL_UNREFERENCED_EVENTS,
    )
    from hermes_db.domains.verification.postgres import record
    fields(payload, {'evidence'})
    evidence = payload['evidence']
    fields(evidence, VerificationEvidence.__dataclass_fields__)
    owned_session(evidence, session_id)
    if type(evidence['exit_code']) is not int or any(not isinstance(value, str) for key, value in evidence.items() if key != 'exit_code'):
        raise RuntimeStoreError('invalid_params')
    created_at = _utc_now()
    cutoff = (datetime.fromisoformat(created_at) - timedelta(days=_MAX_EVIDENCE_AGE_DAYS)).isoformat()
    return record(resource, evidence, created_at, cutoff=cutoff,
                  per_root_limit=_MAX_EVENTS_PER_SESSION_ROOT, total_limit=_MAX_TOTAL_UNREFERENCED_EVENTS)


def write_handlers(metrics_policy=None):
    from hermes_db.domains.runtime.postgres.operations.worker_retain_queue import write_handlers as queue_handlers
    from hermes_db.domains.runtime.postgres.operations.worker_metrics import handlers as metric_handlers
    values = {'domain.verification.' + name: partial(verification, operation=name) for name in ('record', 'mark_edited')}
    values.update(queue_handlers())
    values.update(metric_handlers(metrics_policy))
    return values


def read(conn, scope, session_id, name, arguments):
    from hermes_db.domains.runtime.postgres.operations import worker_retain_queue as queue
    from hermes_db.domains.runtime.postgres.operations import worker_metrics as metrics
    if name in metrics.READS:
        return metrics.read(conn, scope, session_id, name, arguments)
    if name in queue.READS:
        return queue.read(conn, scope, session_id, name, arguments)
    if name != 'verification.status':
        raise RuntimeStoreError('invalid_params')
    return verification(conn, scope, session_id, arguments, operation='status')
