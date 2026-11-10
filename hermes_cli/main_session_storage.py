"""Read-only launch lookups with an explicit backend failure boundary."""

from contextlib import contextmanager
import logging

from hermes_db.errors import StorageError

logger = logging.getLogger(__name__)


@contextmanager
def read_session_store():
    """Yield a read-only ``SessionDB`` (lazy import, so test patches on ``hermes_state``
    intercept). Every caller is a lookup (last session, title → id, recorded cwd), so it
    never opens a writer beside the one the CLI acquires from the registry a moment later.
    Open failures yield None and any error raised by the ``with`` body is swallowed —
    callers fall through to their ``return None``."""
    from hermes_cli.main import get_hermes_home
    db = None
    try:
        from hermes_cli.db_sessions import open_session_store

        db = open_session_store(db_path=get_hermes_home() / "state.db", read_only=True)
    except StorageError:
        raise
    except Exception:
        logger.debug("SQLite launch reader unavailable", exc_info=True)
    try:
        # Gateway rows the CLI/TUI created are labelled ``local``; source-scoped lookups read main's labels.
        from hermes_cli.gateway_session_store import SurfaceLabelReader
        yield SurfaceLabelReader(db) if db is not None else None  # body errors (incl. AttributeError on a None db) are swallowed
    except StorageError:
        raise
    except Exception:
        logger.debug("SQLite launch lookup unavailable", exc_info=True)
    finally:
        if db is not None:
            try:
                db.close()
            except Exception:
                logger.debug("Launch reader close failed", exc_info=True)
