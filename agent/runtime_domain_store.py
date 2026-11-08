"""Named owner-domain calls from adopted compute; no local database or secret selection."""

from pathlib import Path
from types import MappingProxyType

from hermes_db.errors import StorageClosedError
from hermes_db.scope import DatabaseScope


def owner_binding(store):
    from agent.runtime_session_store import WorkerPersistenceError
    cached = getattr(store, '_domain_owner_binding', None)
    if cached is not None:
        return cached
    value = store.owner_read('storage.identity')
    fields = {'version', 'backend', 'profile_home', 'store_id', 'target'}
    if (not isinstance(value, dict) or set(value) != fields or type(value['version']) is not int
            or value['version'] != 1 or value['backend'] not in {'sqlite', 'postgresql'}
            or not isinstance(value['profile_home'], str) or not Path(value['profile_home']).is_absolute()):
        raise WorkerPersistenceError('invalid_owner_storage_identity')
    if value['backend'] == 'postgresql' and any(not isinstance(value[key], str) or not value[key] for key in ('store_id', 'target')):
        raise WorkerPersistenceError('invalid_owner_storage_identity')
    store._domain_owner_binding = MappingProxyType(dict(value))
    return store._domain_owner_binding


def worker_resource(name, *, profile_home=None):
    from agent.runtime_session_store import current_worker_store, is_worker_process, WorkerPersistenceError
    if not is_worker_process():
        return None
    store = current_worker_store()
    binding = owner_binding(store)
    if profile_home is not None and Path(profile_home).resolve() != Path(binding['profile_home']).resolve():
        raise WorkerPersistenceError('permission_denied')
    if binding['backend'] == 'sqlite':
        return None
    return WorkerDomainStore(name, store, binding)


class WorkerDomainStore:
    def __init__(self, name, store, binding):
        self.name, self.store = name, store
        self.scope = DatabaseScope(Path(binding['profile_home']), binding['store_id'])
        self.target = binding['target']
        self._closed = False

    def _assert_open(self):
        if self._closed:
            raise StorageClosedError('Worker domain resource is closed')

    def command(self, name, payload):
        self._assert_open()
        return self.store._apply('domain.' + name, payload)['value']

    def query(self, name, payload):
        self._assert_open()
        return self.store.owner_read('domain.read', name=name, arguments=payload)['value']

    def close(self):
        self._closed = True

    def __enter__(self):
        self._assert_open()
        return self

    def __exit__(self, *_exc):
        self.close()
