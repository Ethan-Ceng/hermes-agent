"""Existing file replacement, capture-pin and short transaction fences survive owner moves."""

from contextlib import contextmanager
from pathlib import Path


def test_replaced_spillover_survives_committed_retirement(core_pair, monkeypatch):
    import hermes_cli.db_media_retirement as media_retirement
    store = core_pair[0]
    path = store.scope.profile_home / "cache" / "spillover" / "replacement.txt"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"old output")
    store.create_session("s", "cli")
    store.append_message("s", "tool", f"Full output saved to: {path}")
    original = media_retirement._collect_spills
    observed = []

    def replace_before_collection(scope, candidates, referenced):
        if candidates:
            path.write_bytes(b"replacement output with a different identity")
            observed.extend(candidates)
        return original(scope, candidates, referenced)

    monkeypatch.setattr(media_retirement, "_collect_spills", replace_before_collection)
    assert store.delete_session("s")
    assert observed
    assert path.read_bytes() == b"replacement output with a different identity"
    assert store.referenced_spillover_names() == set()


def test_capture_retains_media_until_the_last_nested_pin(core_pair):
    from hermes_cli.db_runtime import create_runtime_store
    from gateway.session_ingress_media import capture_lease, capture_native_media
    store = core_pair[0]
    store.scope.profile_home.mkdir(parents=True, exist_ok=True)
    source = store.scope.profile_home / "upload.txt"
    source.write_bytes(b"capture remains held")
    runtime = create_runtime_store(store)
    with store._profile.activate(), capture_lease():
        references = capture_native_media([str(source)])
        path = Path(references[0]["path"])
        with capture_lease():
            repeated = capture_native_media([str(source)])
            assert repeated == references
            assert runtime.release_media(references, retain_history=False) == 0
            assert path.read_bytes() == source.read_bytes()
        assert runtime.release_media(references, retain_history=False) == 0
        assert path.exists()
    assert runtime.release_media(references, retain_history=False) == 1
    assert not path.exists() and source.exists()


def test_archive_unlink_keeps_the_actual_short_write_transaction(core_pair, monkeypatch):
    import hermes_cli.db_archive_files as archive_refs
    from tests.hermes_db.contracts.test_storage_health_refs import _configured
    store = core_pair[0]
    _configured(monkeypatch, store)
    path = store.scope.profile_home / "cache" / "spillover" / "obsolete.txt"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"unreferenced output")
    active, observed = [], []
    original = archive_refs._unlink

    @contextmanager
    def write_scope(settings, scope):
        assert scope == store.scope
        with store._transactions.write() as conn:
            active.append(conn)
            yield conn

    def fenced_unlink(*args):
        observed.append(active[-1].in_transaction())
        return original(*args)

    monkeypatch.setattr(archive_refs, "_write_scope", write_scope)
    monkeypatch.setattr(archive_refs, "_unlink", fenced_unlink)
    assert archive_refs.cleanup_if_postgresql(store.scope.profile_home, [path], cutoff=float("inf")) == 1
    assert observed == [True] and not path.exists()
