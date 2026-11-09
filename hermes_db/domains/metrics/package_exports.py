"""Local package export lifecycle shared by both durable metric backends."""
from pathlib import Path
import logging
logger = logging.getLogger("hermes_cli.observability.shared_metrics")
_BUSY_TIMEOUT_MS = 250

def _ensure_private(path: Path, mode: int) -> None:
    if mode == 0o700:
        path.mkdir(parents=True, exist_ok=True, mode=mode)
    else:
        path.touch(mode=mode, exist_ok=True)
    try:
        path.chmod(mode)
    except OSError:
        pass

class MetricsExport:

    def create_and_export_package_if_due(self) -> list[Path]:
        """Create pending packages at most once per UTC day, then export them."""
        self.drain_deferred(_BUSY_TIMEOUT_MS)
        self._create_pending_packages_if_due()
        return self._export_and_prune()

    def _export_and_prune(self) -> list[Path]:
        exported = self._export_pending_packages()
        try:
            self._prune_expired_history()
        except Exception:
            logger.warning("Unable to prune expired shared-metrics history", exc_info=True)
        return exported
