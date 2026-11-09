"""Independent local Kanban metadata resolves native owner references without PID inference."""

from hermes_db.errors import StorageUnavailableError


def test_kanban_native_owner_reads_configured_scope_and_never_inferrs_remote_pid(core_pair, native_registry, monkeypatch):
    from hermes_cli import kanban_owner_recovery as recovery
    from hermes_db import factory
    from hermes_db.integration.runtime_composition import create_runtime_store
    db, _other = core_pair
    home = db.scope.profile_home
    home.mkdir(parents=True)
    (home / "config.yaml").write_text("storage:\n  backend: postgresql\n  postgresql:\n"
        f"    schema: hermes\n    store_id: {db.scope.store_id}\n")
    (home / ".env").write_text("HERMES_POSTGRES_DSN=postgresql://unused/db\n")
    registry, _opened = native_registry
    monkeypatch.setattr(factory, "acquire_db", lambda settings, scope: registry.acquire(settings.postgresql, scope))
    runtime = create_runtime_store(db)
    db.create_session("owner-session", "kanban")
    epoch = runtime.begin_epoch(instance_id="remote-owner")
    runtime.admit_input(epoch=epoch, principal_id="producer", session_id="owner-session", request_id="attempt", payload={})
    receipt = dict(storage_backend="postgresql", profile_home=str(home), store_id=db.scope.store_id,
        principal_id="producer", session_id="owner-session", request_id="attempt", pid=12345, birth=1.0)
    from hermes_db.core.values import resource_key
    receipt["target"] = resource_key(db._transactions)
    assert recovery._admission_row(receipt) == ("queued", None)
    assert recovery._admission_row(receipt | {"store_id": "another-store"}) is None
    assert recovery._admission_row(receipt | {"target": "another-database"}) is None
    runtime.claim_input(epoch=epoch, session_id="owner-session")
    monkeypatch.setattr(recovery, "_owner_receipt", lambda *args: receipt)
    monkeypatch.setattr(recovery.psutil, "Process", lambda *args: (_ for _ in ()).throw(AssertionError("remote PID probe")))
    assert recovery.owner_reclaim_paused(None, 1)
    assert not recovery._owner_process_gone(receipt)

    def unavailable(*args):
        raise StorageUnavailableError("database offline")

    monkeypatch.setattr(factory, "acquire_db", unavailable)
    assert recovery._admission_row(receipt) is None
    assert not (home / "state.db").exists()
