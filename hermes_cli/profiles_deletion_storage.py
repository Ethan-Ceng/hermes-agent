"""Freeze deletion destinations before displaying a confirmation prompt."""

from dataclasses import dataclass, field

from hermes_db.errors import StorageConfigurationError


@dataclass(frozen=True)
class SelectedStore:
    settings: object = field(repr=False)
    scope: object
    identity: object

    def verify(self):
        if capture(self.scope.profile_home).identity != self.identity:
            raise StorageConfigurationError("Selected database identity changed after the removal plan; preserve all local files")

    def open(self):
        from hermes_db.factory import acquire_db
        from hermes_db.health import storage_identity
        handle = acquire_db(self.settings, self.scope)
        if storage_identity(handle.sessions) != self.identity:
            handle.close()
            raise StorageConfigurationError("Deletion handle does not match the confirmed database")
        return handle


def capture(home):
    from hermes_cli.db_setup import resolve_db_configuration
    settings, scope = resolve_db_configuration(home)
    identity = (scope.profile_home / "state.db").resolve()
    if settings.backend == "postgresql":
        from hermes_db.backends.postgresql.engine import get_engine
        from hermes_db.core.values import resource_key
        from hermes_db.backends.postgresql.transactions import Transactions
        pg = settings.postgresql
        identity = ("postgresql", resource_key(Transactions(get_engine(pg), pg.schema)), scope.require_store_id())
    return SelectedStore(settings, scope, identity)


def identity_token(identity):
    return list(identity) if isinstance(identity, tuple) else str(identity)


@dataclass(frozen=True)
class ProfileDeletion:
    target: SelectedStore
    root: SelectedStore

    def verify(self):
        self.target.verify()
        self.root.verify()

    def purge(self):
        self.verify()
        if self.target.settings.backend == "postgresql":
            from hermes_cli.data_cleanup_storage import StoreRemoval, purge_store
            _, target, store_id = self.target.identity
            purge_store(StoreRemoval(self.target.scope.profile_home, store_id, target), selected=self.target)

    def purge_identity(self, canon, live_mux):
        self.verify()
        root = self.root
        if live_mux:
            from gateway.control_socket import purge_gateway_profile_identity
            token = identity_token(root.identity)
            answer = purge_gateway_profile_identity(root.scope.profile_home, canon, expected_identity=token)
            settled = isinstance(answer, dict) and answer.get("ok") is True and answer.get("storage_identity") == token
            if not settled:
                import sys
                print("⚠ The live gateway could not settle the confirmed routing identity. Restart it, then run:\n"
                    f"    hermes profile purge-identity {canon}", file=sys.stderr)
            return settled
        if root.settings.backend == "sqlite" and not root.identity.is_file():
            return True
        with root.open() as handle:
            handle.sessions.purge_profile_state(canon)
        return True


def prepare(name):
    from hermes_cli import profiles
    from hermes_constants import get_default_hermes_root
    canon = profiles.normalize_profile_name(name)
    if canon == "default":
        raise ValueError("Cannot delete the default profile.\nTo remove everything, use: hermes uninstall")
    canon, home = profiles._existing_profile_dir(canon)
    plan = ProfileDeletion(capture(home), capture(get_default_hermes_root()))
    running, wrapper = profiles._check_gateway_running(home), profiles._find_our_wrapper(canon)
    return canon, home, running, wrapper, plan
