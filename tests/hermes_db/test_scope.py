"""Logical identity cannot accidentally become a host-local path."""

from dataclasses import FrozenInstanceError

import pytest

from hermes_db.errors import StorageConfigurationError
from hermes_db.scope import DatabaseScope


def test_scope_has_stable_logical_identity_and_is_immutable(tmp_path):
    one = DatabaseScope(tmp_path / "node-one", "store-a")
    two = DatabaseScope(tmp_path / "node-two", "store-a")
    assert one.require_store_id() == two.require_store_id()
    assert one.profile_home != two.profile_home
    with pytest.raises(FrozenInstanceError):
        one.store_id = "other"


@pytest.mark.parametrize("store_id", ["", "/host/profile", "D:\\profile", "../other", "nul\x00key", 7])
def test_path_and_invalid_store_id_are_rejected(tmp_path, store_id):
    with pytest.raises(StorageConfigurationError):
        DatabaseScope(tmp_path, store_id)


def test_scope_does_not_invent_a_postgres_identity(tmp_path):
    with pytest.raises(StorageConfigurationError, match="store_id is required"):
        DatabaseScope(tmp_path).require_store_id()
