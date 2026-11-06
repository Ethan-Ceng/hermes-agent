"""Credential-safe config parsing and fail-closed namespace ownership."""

from unittest.mock import MagicMock

import pytest

from tests.hermes_db.pg_support import (
    PostgresTestError, isolated_namespace, read_test_config, verify_database,
)


def _config(tmp_path, text=None):
    path = tmp_path / "postgresql.yaml"
    path.write_text(text if text is not None else
                    "purpose: hermes-postgresql-tests\ndatabase: hermes_test\n"
                    "dsn: postgresql://u:private-password@localhost/hermes_test\n", encoding="utf-8")
    return path


def test_config_is_explicit_and_secret_repr_is_safe(tmp_path):
    config = read_test_config(str(_config(tmp_path)))
    assert config.database == "hermes_test"
    assert config.settings.pool_size + config.settings.max_overflow == 2
    assert "private-password" not in repr(config)


@pytest.mark.parametrize("contents", [
    "[bad YAML: {dsn: private-password", "{}", "purpose: other",
    "purpose: hermes-postgresql-tests\ndatabase: postgres\ndsn: private-password",
    "purpose: hermes-postgresql-tests\ndatabase: hermes_test",
    "purpose: hermes-postgresql-tests\ndatabase: hermes_test\ndsn: private-password",
])
def test_bad_config_fails_without_disclosing_its_contents(tmp_path, contents):
    with pytest.raises(PostgresTestError) as error:
        read_test_config(str(_config(tmp_path, contents)))
    assert "private-password" not in str(error.value)


def test_missing_config_and_wrong_database_do_not_turn_into_skips(tmp_path):
    for path in (None, str(tmp_path / "absent.yaml")):
        with pytest.raises(PostgresTestError):
            read_test_config(path)
    with pytest.raises(PostgresTestError, match="does not match"):
        verify_database("business", "hermes_test")


def _namespace_pool(responses):
    from sqlalchemy.dialects.postgresql import dialect

    pool = MagicMock()
    conn = pool.begin.return_value.__enter__.return_value
    conn.scalar.side_effect = responses
    conn.dialect = dialect()
    return pool, conn


def test_existing_namespace_is_never_adopted_or_deleted(tmp_path):
    pytest.importorskip("sqlalchemy", reason="optional postgresql extra")
    config = read_test_config(str(_config(tmp_path)))
    pool, conn = _namespace_pool(["hermes_test", 42])
    with pytest.raises(PostgresTestError, match="already exists"):
        with isolated_namespace(pool, config):
            pytest.fail("namespace must not be yielded")
    conn.execute.assert_not_called()


def test_changed_owner_marker_prevents_schema_drop(tmp_path):
    pytest.importorskip("sqlalchemy", reason="optional postgresql extra")
    from sqlalchemy.schema import DropSchema

    config = read_test_config(str(_config(tmp_path)))
    pool, conn = _namespace_pool(["hermes_test", None, "other-owner"])
    with pytest.raises(PostgresTestError, match="ownership changed"):
        with isolated_namespace(pool, config) as schema:
            assert schema.startswith("hermes_test_")
    assert not any(isinstance(call.args[0], DropSchema) for call in conn.execute.call_args_list)


def test_own_namespace_is_cleaned_after_test_failure(tmp_path):
    pytest.importorskip("sqlalchemy", reason="optional postgresql extra")
    from sqlalchemy.schema import DropSchema

    config = read_test_config(str(_config(tmp_path)))
    pool, conn = _namespace_pool(["hermes_test", None])
    with pytest.raises(ValueError, match="test failed"):
        with isolated_namespace(pool, config) as schema:
            conn.scalar.side_effect = ["hermes-pg-tests:" + schema.removeprefix("hermes_test_")]
            raise ValueError("test failed")
    drops = [call.args[0] for call in conn.execute.call_args_list if isinstance(call.args[0], DropSchema)]
    assert len(drops) == 1
    assert drops[0].element == schema
