"""Publishing a new profile never makes it another PG profile's logical store."""

from pathlib import Path

import pytest
import hermes_yaml as yaml


@pytest.mark.parametrize("clone_all", [False, True])
def test_pg_profile_clones_have_new_store_and_file_owner_identities(tmp_path, monkeypatch, clone_all):
    import hermes_constants
    from hermes_cli import profiles
    from hermes_db.core.file_scope import owner_id
    root = tmp_path / ".hermes"
    root.mkdir()
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(root))
    monkeypatch.setattr(hermes_constants, "_default_hermes_root_memo", None)
    monkeypatch.setattr(profiles, "_maybe_register_gateway_service", lambda name: None)
    monkeypatch.setattr(profiles, "_notify_multiplexer", lambda name: None)
    config = {"storage": {"backend": "postgresql", "postgresql": {
        "schema": "shared", "store_id": "source-store", "dsn_env": "PROFILE_PG_DSN"}},
        "model": {"provider": "custom", "default": "model"}}
    (root / "config.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    (root / ".env").write_text("PROFILE_PG_DSN=postgresql://never-connected/db\n", encoding="utf-8")
    original_owner = owner_id(root, create=True)
    made = [profiles.create_profile(name, clone_config=not clone_all, clone_all=clone_all,
        clone_channels=True, no_alias=True) for name in ("one", "two")]
    settings = [yaml.safe_load((home / "config.yaml").read_text(encoding="utf-8")) for home in made]
    ids = [item["storage"]["postgresql"]["store_id"] for item in settings]
    assert len({"source-store", *ids}) == 3
    assert len({original_owner, *(owner_id(home, create=True) for home in made)}) == 3
    for item in settings:
        assert item["storage"]["postgresql"]["schema"] == "shared"
        assert item["storage"]["postgresql"]["dsn_env"] == "PROFILE_PG_DSN"
    assert yaml.safe_load((root / "config.yaml").read_text())["storage"]["postgresql"]["store_id"] == "source-store"
    assert owner_id(root) == original_owner
    assert not any((home / "state.db").exists() for home in [root, *made])
