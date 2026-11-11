"""Persisted file grants protect normal reads and collection without any mover."""

import uuid

import pytest


def _existing_grant(source, target, *, spillover=(), media=()):
    from hermes_db.core.file_scope import owner_id
    from hermes_db.domains.sessions.postgres.queries import file_grants

    source.scope.profile_home.mkdir(parents=True, exist_ok=True)
    grant_id = uuid.uuid4().hex
    value = {"version": 1, "grant_id": grant_id, "token": uuid.uuid4().hex,
             "origin_store_id": source.scope.require_store_id(),
             "origin_home": str(source.scope.profile_home),
             "file_owner_id": owner_id(source.scope.profile_home, create=True),
             "recipient_store_id": target.scope.require_store_id(),
             "files": {"spillover": list(spillover), "media": list(media)}}
    with source._transactions.write() as conn:
        file_grants.put(conn, source.scope, file_grants.OWNED + grant_id, value)
        file_grants.put(conn, target.scope, file_grants.RECEIVED + grant_id, value)
    return value


def _spillover(pair):
    source, target = pair
    path = source.scope.profile_home / "cache" / "spillover" / "existing.txt"
    path.parent.mkdir(parents=True)
    path.write_text("retained full output", encoding="utf-8")
    for store in pair:
        store.create_session("s", "cli")
        store.append_message("s", "tool", f"Full output saved to: {path}")
    proof = _existing_grant(source, target, spillover=[path.name])
    return path, proof


def test_existing_spillover_grant_pins_until_last_recipient_history(core_pair):
    source, target = core_pair
    path, _ = _spillover(core_pair)
    assert source.delete_session("s") and path.exists()
    assert source.referenced_spillover_names() == {path.name}
    exported = target.export_session("s", include_inactive=True)
    assert str(path) in exported["messages"][0]["content"]
    exported.update(id="fork", parent_session_id=None, title=None)
    assert target.import_sessions([exported])["imported"] == 1
    assert target.delete_session("s") and path.exists()
    assert target.delete_session("fork")
    assert not path.exists() and source.referenced_spillover_names() == set()


@pytest.mark.parametrize("changed", ["token", "recipient_store_id"])
def test_unverified_existing_grant_retains_origin_file(core_pair, changed):
    from hermes_db.domains.sessions.postgres.queries import file_grants

    source, target = core_pair
    path, proof = _spillover(core_pair)
    with source._transactions.write() as conn:
        scope, prefix = (target.scope, file_grants.RECEIVED) if changed == "token" else (source.scope, file_grants.OWNED)
        file_grants.put(conn, scope, prefix + proof["grant_id"], {**proof, changed: uuid.uuid4().hex})
    assert source.delete_session("s") and path.exists()
    assert target.delete_session("s") and path.exists()
    assert source.referenced_spillover_names() == {path.name}


def test_existing_grant_does_not_collect_changed_file_owner(core_pair):
    source, target = core_pair
    path, _ = _spillover(core_pair)
    assert source.delete_session("s") and path.exists()
    (source.scope.profile_home / ".file-store-id").write_text(uuid.uuid4().hex, encoding="ascii")
    assert target.delete_session("s")
    assert path.read_text(encoding="utf-8") == "retained full output"


def test_existing_media_grant_protects_normal_release(core_pair):
    import hashlib
    from hermes_cli.db_runtime import create_runtime_store
    from gateway.session_ingress_media import native_inputs_root

    source, target = core_pair
    with source._profile.activate():
        root = native_inputs_root()
    digest = hashlib.sha256(b"retained media").hexdigest()
    path = root / digest / "note.txt"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"retained media")
    reference = {"path": str(path), "sha256": digest}
    target.create_session("s", "cli")
    target.append_message("s", "user", str(path))
    _existing_grant(source, target, media=[reference])
    assert create_runtime_store(source).release_media([reference], retain_history=False) == 0
    assert path.read_bytes() == b"retained media"
    assert target.delete_session("s")
    assert create_runtime_store(source).release_media([reference], retain_history=False) == 1
    assert not path.exists()
