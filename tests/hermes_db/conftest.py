"""A path-only opt-in: the standard runner never inherits application DSNs."""

import pytest


def pytest_addoption(parser):
    parser.addoption("--postgres-test-config", default=None, metavar="PATH",
                     help="Local secret config for an independent PostgreSQL test database")
    parser.addoption("--hermes-distribution-source", default=None, metavar="PATH",
                     help="Independent source-bundle payload to verify outside the development import path")
    for backend in ("sqlite", "postgresql", "sqlite-matrix"):
        parser.addoption(f"--hermes-{backend}-python", default=None, metavar="PATH",
                         help=f"PM-built interpreter for the {backend} distribution payload")


@pytest.fixture(scope="session")
def postgres_test_config(request):
    from tests.hermes_db.pg_support import read_test_config

    return read_test_config(request.config.getoption("--postgres-test-config"))


@pytest.fixture(scope="session")
def postgres_engine(postgres_test_config):
    from hermes_db.infra.backends.postgresql.engine import close_engines, get_engine, read_connection
    from tests.hermes_db.pg_support import probe_environment

    try:
        with read_connection(postgres_test_config.settings) as conn:
            probe_environment(conn, postgres_test_config)
        yield get_engine(postgres_test_config.settings)
    finally:
        close_engines()


@pytest.fixture
def postgres_schema(postgres_engine, postgres_test_config):
    from tests.hermes_db.pg_support import isolated_namespace

    with isolated_namespace(postgres_engine, postgres_test_config) as schema:
        yield schema
