"""Native session behavior with an application-captured activation scope."""

from hermes_db.domains.resource import _bound_method





class SQLiteSessions:
    def __init__(self, db, scope, *, activate, runtime):
        self._db, self._scope = db, scope
        self._activate = activate
        self.runtime = runtime

    def __getattr__(self, name):
        value = getattr(self._db, name)
        return _bound_method(self._activate, value) if callable(value) else value
