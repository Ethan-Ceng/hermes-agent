"""Real service evidence, excluded by default and never skipped when selected."""

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def test_environment_and_disposable_namespace(postgres_engine, postgres_test_config,
                                              postgres_schema, record_property):
    import psycopg
    from sqlalchemy import text
    from tests.hermes_db.pg_support import probe_environment

    with postgres_engine.connect() as conn:
        evidence = probe_environment(conn, postgres_test_config)
        assert conn.scalar(text("SELECT nspname FROM pg_namespace WHERE nspname=:name"),
                           {"name": postgres_schema}) == postgres_schema
    evidence["psycopg_version"] = psycopg.__version__
    for name, value in evidence.items():
        record_property(name, str(value))
    # Runner output records capabilities even without a JUnit output file.
    print("PostgreSQL environment:", evidence)
