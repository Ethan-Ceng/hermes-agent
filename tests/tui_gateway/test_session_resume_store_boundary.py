"""Resume resolves only the owning dataset; normal local recovery is preserved."""

import importlib
from unittest.mock import MagicMock, patch

import pytest

from hermes_state import SessionDB


@pytest.fixture()
def gateway(tmp_path, monkeypatch):
    from pathlib import Path as _P

    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setattr(_P, "home", lambda: tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(home))

    with patch.dict(
        "sys.modules",
        {
            "hermes_cli.env_loader": MagicMock(),
            "hermes_cli.banner": MagicMock(),
        },
    ):
        mod = importlib.import_module("tui_gateway.server")

    methods = dict(mod._methods)

    default_db = SessionDB(db_path=home / "state.db")
    mod._db = default_db

    profile_home = home / "profiles" / "developer"
    profile_home.mkdir(parents=True)

    # session.resume resolves the profile via hermes_cli.profiles
    monkeypatch.setattr(
        "hermes_cli.profiles.get_profile_dir", lambda name: str(profile_home)
    )

    yield mod, default_db, profile_home

    mod._methods.clear()
    mod._methods.update(methods)
    mod._sessions.clear()
    __import__("tui_gateway.server_requests", fromlist=["x"]).reset_for_tests()
    mod._db = None
    default_db.close()



def _seed(db, sid, title):
    db.create_session(sid, source="tui")
    db.set_session_title(sid, title)
    db.append_message(sid, "user", "history in " + title)
    db.append_message(sid, "assistant", "answer in " + title)


def _resume(mod, target, profile="developer"):
    params = {"session_id": target, "lazy": True}
    if profile is not None:
        params["profile"] = profile
    return mod.handle_request({"id": "resume", "method": "session.resume", "params": params})


@pytest.mark.parametrize("archived", [False, True])
def test_resume_does_not_read_or_copy_another_store(gateway, monkeypatch, archived):
    mod, donor, profile_home = gateway
    sid = "legacy-other-store"
    _seed(donor, sid, "Other dataset")
    if archived:
        donor.set_session_archived(sid, True)
    before = donor.export_session(sid, include_inactive=True)
    lookup = MagicMock(wraps=donor.get_session)
    with monkeypatch.context() as scoped:
        scoped.setattr(donor, "get_session", lookup)
        response = _resume(mod, sid)
    assert response.get("error", {}).get("code") == 4007
    lookup.assert_not_called()
    assert donor.export_session(sid, include_inactive=True) == before
    with SessionDB(db_path=profile_home / "state.db") as owned:
        assert owned.get_session(sid) is None
        assert owned.get_messages(sid) == []


@pytest.mark.parametrize("target", ["owned-id", "Owned title"])
def test_resume_uses_owned_id_or_title_without_reading_other_store(gateway, monkeypatch, target):
    mod, donor, profile_home = gateway
    _seed(donor, "owned-id", "Other dataset")
    before = donor.export_session("owned-id", include_inactive=True)
    with SessionDB(db_path=profile_home / "state.db") as owned:
        _seed(owned, "owned-id", "Owned title")
    lookup = MagicMock(wraps=donor.get_session)
    with monkeypatch.context() as scoped:
        scoped.setattr(donor, "get_session", lookup)
        response = _resume(mod, target)
    assert not response.get("error")
    assert response["result"]["resumed"] == "owned-id"
    assert response["result"]["message_count"] == 2
    lookup.assert_not_called()
    assert donor.export_session("owned-id", include_inactive=True) == before


@pytest.mark.parametrize("profile", ["developer", None])
def test_unknown_session_keeps_not_found_result(gateway, profile):
    mod, _, _ = gateway
    assert _resume(mod, "unknown-unminted-id", profile).get("error", {}).get("code") == 4007
