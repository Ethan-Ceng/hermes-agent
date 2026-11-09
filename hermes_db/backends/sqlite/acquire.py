"""Reuse the SQLite registry and its existing runtime semantics."""

from functools import wraps

from hermes_db.handle import DatabaseHandle
from hermes_db.scope import DatabaseScope, bind_profile_home


_RUNTIME_FUNCTIONS = {
    "begin_epoch": "begin_runtime_epoch",
    "admit_input": "admit_session_input",
    "get_admission": "get_session_admission",
    "find_admission": "find_session_admission",
    "list_admissions": "list_session_admissions",
    "claim_input": "claim_session_input",
    "settle_input": "settle_session_input",
    "cancel_input": "cancel_session_input",
    "steer_input": "steer_session_input",
    "revert_steer": "revert_steer_input",
    "rehome_inputs": "rehome_queued_inputs",
    "retarget_automation": "retarget_local_automation",
    "recover_inputs": "recover_session_inputs",
    "mutate_session": "mutate_runtime_session",
    "resolve_unknown": "resolve_unknown_session_input",
    "register_worker": "register_worker_execution",
    "adopt_worker": "adopt_worker_execution",
    "mutate_worker": "mutate_worker_execution",
    "apply_worker_receipt": "apply_worker_receipt",
}


class SQLiteRuntime:
    def __init__(self, db, scope):
        self._db = db
        self._scope = scope

    def __getattr__(self, name):
        function = _RUNTIME_FUNCTIONS.get(name)
        if function is None:
            raise AttributeError(name)
        import hermes_state_runtime

        return _bound_method(self._scope, getattr(hermes_state_runtime, function), self._db)


def _bound_method(scope, function, *bound):
    @wraps(function)
    def call(*args, **kwargs):
        with bind_profile_home(scope):
            return function(*bound, *args, **kwargs)
    return call


class SQLiteSessions:
    def __init__(self, db, scope):
        self._db, self._scope = db, scope

    def __getattr__(self, name):
        value = getattr(self._db, name)
        return _bound_method(self._scope, value) if callable(value) else value


def acquire_sqlite(scope: DatabaseScope) -> DatabaseHandle:
    from hermes_state_registry import acquire, release

    with bind_profile_home(scope):
        db = acquire(scope.profile_home / "state.db")
    return DatabaseHandle(scope, SQLiteSessions(db, scope), SQLiteRuntime(db, scope),
                          _bound_method(scope, release, db))
