"""Application-owned Profile and secret binding for captured storage operations."""
from contextlib import contextmanager
from pathlib import Path
from hermes_db.scope import DatabaseScope


def _bind_storage_state(home, secrets=None):
    from agent.runtime_scope import bind_state, scope_for_profile
    from hermes_scope import current_state
    scope = scope_for_profile(home)
    state = current_state()
    # A nested storage operation keeps the turn's frozen terminal policy.
    policy = state.terminal if state.scope is scope else None
    return bind_state(scope, secrets=secrets, hydrate_secrets=False,
                      terminal_policy=policy, defer_terminal=True)


@contextmanager
def bind_profile_home(scope: DatabaseScope):
    """Bind deferred SQLite policy reads as one scope change, without changing process env."""
    from agent.secret_scope import current_secret_scope, current_secret_scope_home
    home = current_secret_scope_home()
    secrets = current_secret_scope() if home and Path(home).resolve() == scope.profile_home else None
    with _bind_storage_state(scope.profile_home, secrets):
        yield


class OwnedProfileContext:
    def __init__(self, scope):
        from agent.secret_scope import current_secret_scope, current_secret_scope_home
        self.scope = scope
        home = current_secret_scope_home()
        self._secrets = dict(current_secret_scope() or {}) if home and Path(home).resolve() == scope.profile_home else {}

    @contextmanager
    def activate(self):
        from agent.secret_scope import (
            current_secret_scope, current_secret_scope_home, set_multiplex_context, reset_multiplex_context,
        )
        home = current_secret_scope_home()
        secrets = current_secret_scope() if home and Path(home).resolve() == self.scope.profile_home else self._secrets
        with _bind_storage_state(self.scope.profile_home, secrets):
            routed = set_multiplex_context(True)
            try:
                yield
            finally:
                reset_multiplex_context(routed)
