"""Moved native receipt ownership retains stored-row and profile isolation; PG store ids stay exact."""
import copy
import json
from types import SimpleNamespace

import pytest

from gateway.session_receipt_ownership import validate_receipt_profile
from hermes_db.domains.runtime.receipts import API_BINDING_PREFIX
from hermes_db.scope import DatabaseScope
from hermes_state_runtime import RuntimeStoreError
from tests.gateway.test_moved_store_session_restore import _serving
from tests.gateway.test_session_authorities_multiplex import _reserve_homes


@pytest.mark.asyncio
async def test_moved_native_receipt_requires_its_own_profile_route_and_stored_row(tmp_path, monkeypatch):
    from gateway.session_api import bind_api_session
    root, homes = _reserve_homes(tmp_path, monkeypatch)
    async with _serving(root, homes, homes[1][1]) as authority:
        authority.db.create_session("moved", source="api_server")
        bind_api_session(authority, "moved")
        receipt = json.loads(authority.db.get_meta(API_BINDING_PREFIX + "moved"))
        receipt["profile_id"] = "/departed/host/profiles/alpha"
        validate_receipt_profile(authority, receipt)
        for field, value in (("profile", "beta"), ("user_id", "other"), ("chat_id", "other")):
            foreign = copy.deepcopy(receipt)
            foreign["entry"]["origin"][field] = value
            with pytest.raises(RuntimeStoreError, match="profile_mismatch"):
                validate_receipt_profile(authority, foreign)
        for field, value in (("route", "agent:beta:foreign"), ("session_id", "missing")):
            foreign = {**receipt, field: value}
            with pytest.raises(RuntimeStoreError, match="profile_mismatch"):
                validate_receipt_profile(authority, foreign)


def test_postgresql_receipt_requires_the_exact_captured_dataset(tmp_path):
    authority = SimpleNamespace(db=SimpleNamespace(scope=DatabaseScope(tmp_path, "own-store")))
    validate_receipt_profile(authority, {"profile_id": "pg-store:own-store"})
    with pytest.raises(RuntimeStoreError, match="profile_mismatch"):
        validate_receipt_profile(authority, {"profile_id": "pg-store:foreign-store"})
