"""Application-owned Profile and secret binding for captured storage operations."""

from contextlib import contextmanager
from pathlib import Path

from hermes_db.scope import DatabaseScope


@contextmanager
def bind_profile_home(scope: DatabaseScope):
    """Bind deferred SQLite configuration reads without changing process env."""
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override

    token = set_hermes_home_override(scope.profile_home)
    try:
        yield
    finally:
        reset_hermes_home_override(token)


class OwnedProfileContext:
    def __init__(self, scope):
        from agent.secret_scope import current_secret_scope, current_secret_scope_home

        self.scope = scope
        home = current_secret_scope_home()
        self._secrets = dict(current_secret_scope() or {}) if home and Path(home).resolve() == scope.profile_home else {}

    @contextmanager
    def activate(self):
        from agent.secret_scope import (
            current_secret_scope, current_secret_scope_home, set_secret_scope, reset_secret_scope,
            set_multiplex_context, reset_multiplex_context,
        )

        home = current_secret_scope_home()
        secrets = current_secret_scope() if home and Path(home).resolve() == self.scope.profile_home else self._secrets
        with bind_profile_home(self.scope):
            secret = set_secret_scope(secrets, profile_home=str(self.scope.profile_home))
            routed = set_multiplex_context(True)
            try:
                yield
            finally:
                reset_multiplex_context(routed)
                reset_secret_scope(secret)
