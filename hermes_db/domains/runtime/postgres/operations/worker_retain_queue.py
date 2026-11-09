"""Closed RetainDB namespace operations; the owner connection defines the dataset."""

from dataclasses import dataclass
from functools import partial

from hermes_db.domains.plugin_storage.retain.postgres.operations import queue as operations
from hermes_db.domains.runtime.postgres.operations.worker_domains import fields, text
from hermes_state_runtime import RuntimeStoreError

READS = frozenset({'retain_queue.inspect', 'retain_queue.counts', 'retain_queue.ready', 'retain_queue.owns_claim'})
WRITES = frozenset({'enqueue', 'claim', 'renew', 'acknowledge', 'fail'})
_FIELDS = {
    'enqueue': {'request_id', 'user_id', 'session_id', 'messages'}, 'claim': set(),
    'renew': {'request_id', 'token'}, 'acknowledge': {'request_id', 'token'},
    'fail': {'request_id', 'token', 'error'}, 'inspect': {'request_id'}, 'counts': set(), 'ready': set(),
    'owns_claim': {'request_id', 'token'},
}


@dataclass(frozen=True)
class QueueNamespace:
    store_id: str
    destination_id: str
    plugin_id: str = 'retaindb'


def invoke(conn, scope, session_id, payload, *, operation):
    fields(payload, _FIELDS[operation] | {'destination_id'})
    destination = payload['destination_id']
    if not isinstance(destination, str) or len(destination) != 64 or any(char not in '0123456789abcdef' for char in destination):
        raise RuntimeStoreError('invalid_params')
    reference = QueueNamespace(scope.require_store_id(), destination)
    for name in _FIELDS[operation] - {'messages'}:
        if name in {'request_id', 'token'}:
            text(payload[name])
        elif not isinstance(payload[name], str):
            raise RuntimeStoreError('invalid_params')
    if operation == 'enqueue':
        if not isinstance(payload['messages'], list):
            raise RuntimeStoreError('invalid_params')
        record = operations.prepare(reference, payload['request_id'], payload['user_id'], payload['session_id'], payload['messages'])
        result = operations.enqueue(reference, record, connection=conn)
    else:
        arguments = {key: payload[key] for key in _FIELDS[operation]}
        result = getattr(operations, operation)(reference, **arguments, connection=conn)
    if isinstance(result, dict) and isinstance(result.get('fingerprint'), (bytes, memoryview)):
        result = dict(result, fingerprint=bytes(result['fingerprint']).hex())
    return {'value': result}


def write_handlers():
    return {'domain.retain_queue.' + name: partial(invoke, operation=name) for name in WRITES}


def read(conn, scope, session_id, name, arguments):
    if name not in READS:
        raise RuntimeStoreError('invalid_params')
    return invoke(conn, scope, session_id, arguments, operation=name.split('.', 1)[1])
