"""Selected-backend exit diagnostics; journal and physical integrity scans are SQLite-only."""

import logging
from pathlib import Path

logger = logging.getLogger("gateway.lifecycle_ledger")


def configured_integrity(home):
    from hermes_constants import get_hermes_home
    from hermes_cli.db_diagnostics import configured_probe
    result = configured_probe(Path(home) if home is not None else get_hermes_home())
    if result is None:
        return None
    return "ok" if result["status"] == "ok" else f"check-failed: {result.get('detail', 'selected database unavailable')}"


def deferred_integrity(home, deadline_s):
    from gateway import lifecycle_ledger as ledger
    configured = configured_integrity(home)
    if configured is not None:
        return configured
    path = ledger._home_path(home, "state.db")
    mode = ledger._state_db_journal_mode(path) if path.exists() else "wal"
    if mode == "wal":
        return ledger.check_state_db_integrity(home=home, deadline_s=deadline_s)
    logger.warning(
        "Previous gateway exit was unclean, but the state.db integrity check was skipped: %s is a "
        "rollback-journal store (journal_mode=%s) and a background scan would block live writes. "
        "To check it, stop the gateway and run: sqlite3 %s 'PRAGMA quick_check'", path, mode or "unknown", path)
    return f"skipped: rollback-journal store (journal_mode={mode or 'unknown'}), scan would block live writes"
