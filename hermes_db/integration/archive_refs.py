"""Profile-bound archive reads and short fenced local cleanup, with no SQLite fallback."""

from contextlib import contextmanager
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


@contextmanager
def _read_scope(settings, scope):
    from hermes_db.infra.backends.postgresql.engine import read_connection
    from hermes_cli.db_scope import OwnedProfileContext
    from hermes_db.tables.metadata import SCHEMA
    with OwnedProfileContext(scope).activate(), read_connection(settings) as conn:
        yield conn.execution_options(schema_translate_map={SCHEMA: settings.schema})


@contextmanager
def _write_scope(settings, scope):
    from hermes_db.infra.backends.postgresql.engine import get_engine
    from hermes_db.infra.backends.postgresql.transactions import Transactions
    from hermes_db.tables.metadata import SCHEMA
    from hermes_cli.db_scope import OwnedProfileContext
    transactions = Transactions(get_engine(settings), settings.schema,
        lock_timeout=settings.write_lock_timeout_seconds, statement_timeout=settings.statement_timeout_seconds, schema_token=SCHEMA)
    with OwnedProfileContext(scope).activate(), transactions.write() as conn:
        yield conn


def for_profile(home):
    from hermes_cli.db_setup import resolve_db_configuration
    settings, scope = resolve_db_configuration(home)
    if settings.backend == "sqlite":
        return False, None
    from hermes_db.domains.sessions.postgres.queries.archive_refs import referenced_names
    with _read_scope(settings.postgresql, scope) as conn:
        return True, referenced_names(conn, scope)


def cleanup_if_postgresql(home, paths, *, cutoff):
    from hermes_cli.config_backend import ConfigBackendUnavailable
    from hermes_cli.db_setup import resolve_db_configuration
    try:
        settings, scope = resolve_db_configuration(home)
        if settings.backend == "sqlite":
            return None
        from hermes_db.domains.sessions.postgres.queries import archive_refs, sessions
        with _write_scope(settings.postgresql, scope) as conn:
            sessions.lock_store(conn, scope, exclusive=True)
            names = archive_refs.referenced_names(conn, scope)
            return _unlink(scope.profile_home / "cache" / "spillover", paths, names, cutoff)
    except (ConfigBackendUnavailable, Exception) as exc:  # health: allow BLE001 -- unknown ownership/references must preserve every file
        logger.debug("PG archive cleanup deferred (%s)", type(exc).__name__)
        return 0


def _unlink(root, paths, referenced, cutoff):
    if referenced is None:
        return 0
    root, removed = root.resolve(), 0
    for path in paths:
        path = Path(path)
        if path.name in referenced or path.resolve().parent != root:
            continue
        try:
            if path.stat().st_mtime >= cutoff:
                continue
            path.unlink()
            removed += 1
        except OSError:
            logger.debug("Archive cleanup deferred for a local file", exc_info=True)
    return removed
