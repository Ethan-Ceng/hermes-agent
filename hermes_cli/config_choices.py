"""Apply explicit user setting choices after the owning config write."""

from pathlib import Path


def apply_written_setting(key: str, value, profile_home: Path) -> None:
    if key == "display.skin" and isinstance(value, str) and value:
        try:
            skin_file = profile_home / "skins" / f"{value}.yaml"
            if skin_file.exists():
                skin_file.touch()
        except OSError:
            # Re-applying a skin is best-effort, as in the original config setter.
            return
    if key == "display.language":
        from agent.i18n import reset_language_cache
        reset_language_cache()
    if key in {"telemetry.shared_metrics.enabled", "telemetry.shared_metrics.send"} and value is True:
        from hermes_cli.db_setup import _storage_config
        from hermes_cli.observability.shared_metrics import SharedMetricsStore

        config = _storage_config(profile_home)
        if ((config.get("telemetry") or {}).get("shared_metrics") or {}).get("enabled") is True:
            SharedMetricsStore.create(profile_home=profile_home)
