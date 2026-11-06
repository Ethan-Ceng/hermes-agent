"""The installed migration tree and application version contract must agree."""

from pathlib import Path

import pytest


def test_alembic_can_discover_the_required_frozen_revision():
    pytest.importorskip("alembic", reason="optional postgresql extra")
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from hermes_db import migrations
    from hermes_db.schema import REQUIRED_REVISION

    directory = Path(migrations.__file__).parent
    config = Config(str(directory / "alembic.ini"))
    config.set_main_option("script_location", str(directory).replace("%", "%%"))
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == [REQUIRED_REVISION]
    assert script.get_revision(REQUIRED_REVISION).down_revision is None


def test_upgrade_pool_timeout_is_a_redacted_storage_failure(monkeypatch):
    sa = pytest.importorskip("sqlalchemy", reason="optional postgresql extra")
    pytest.importorskip("psycopg", reason="optional postgresql extra")
    from unittest.mock import Mock
    from hermes_db import schema
    from hermes_db.errors import StorageUnavailableError
    from hermes_db.settings import PostgresSettings

    pool = Mock()
    pool.begin.side_effect = sa.exc.TimeoutError("private connection details")
    monkeypatch.setattr(schema, "get_engine", lambda _: pool)
    with pytest.raises(StorageUnavailableError) as error:
        schema.upgrade_schema(PostgresSettings("postgresql://localhost/unused", "hermes"))
    assert "private connection details" not in str(error.value)
