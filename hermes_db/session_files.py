"""Post-commit removal of session snapshots, confined to the configured directory."""

import glob
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def remove(sessions_dir, session_ids):
    if sessions_dir is None:
        return
    base = Path(sessions_dir).resolve()
    for session_id in session_ids:
        targets = [base / f"{session_id}{suffix}" for suffix in (".json", ".jsonl")]
        targets.append(base / f"session_{session_id}.json")
        if Path(session_id).name == session_id and "/" not in session_id and "\\" not in session_id:
            try:
                targets.extend(base.glob(f"request_dump_{glob.escape(session_id)}_*.json"))
            except OSError:
                logger.warning("Session dump lookup failed after committed deletion", exc_info=True)
        for target in targets:
            try:
                if target.resolve().is_relative_to(base):
                    target.unlink(missing_ok=True)
            except OSError:
                logger.warning("Session snapshot cleanup failed after committed deletion", exc_info=True)
