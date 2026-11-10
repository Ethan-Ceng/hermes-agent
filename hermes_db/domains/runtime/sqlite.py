"""Native runtime business dispatch with an application-captured scope."""

from hermes_db.domains.resource import _bound_method


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
    def __init__(self, db, scope, *, activate, resolve):
        self._db = db
        self._scope = scope
        self._activate = activate
        self._resolve = resolve

    def __getattr__(self, name):
        function = _RUNTIME_FUNCTIONS.get(name)
        if function is None:
            raise AttributeError(name)
        return _bound_method(self._activate, self._resolve(function), self._db)
