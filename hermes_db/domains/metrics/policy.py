"""Backend-independent metric validation, signal names and package projections."""
from __future__ import annotations
import json
import logging
from datetime import datetime, timedelta, UTC
from typing import Any
from collections.abc import Mapping
from hermes_cli.observability.shared_metrics_contract import (
    CLIENT_ACTIVE_METRIC,
    COUNTER_METRICS,
    FEATURE_ADOPTION_METRIC,
    INSTALL_SNAPSHOT_METRIC,
    MILESTONE_METRIC,
    MODEL_ROUTE_METRIC,
    SUM_METRICS,
    client_resource_is_valid,
    counter_dimensions_are_valid,
)

from hermes_cli.observability.shared_metrics_drift import conform_counter_dimensions, counter_dimensions_shape_is_known

logger = logging.getLogger("hermes_cli.observability.shared_metrics")

_SCHEMA_BUSY_TIMEOUT_MS = 5_000
_PACKAGE_SCHEMA_VERSION = "hermes.shared_metrics.v4"

_LOCAL_HISTORY_RETENTION_DAYS = 30

_ACTIVE_INSTALL_STATE_KEY = "client_active_recorded_at"

_INSTALL_SNAPSHOT_STATE_KEY = "install_snapshot_recorded_at"

_MILESTONE_STATE_PREFIX = "milestone:"

_FEATURE_STATE_PREFIX = "feature:"

_DAILY_ONCE_STATE_PREFIX = "daily_once:"

_ACTIVE_INSTALL_INTERVAL = timedelta(hours=24)

def _utc_now() -> datetime:
    return datetime.now(UTC)

def _isoformat(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")

def _compact_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


class MetricsPolicy:

    def record_model_call(self, dimensions: dict[str, str], resource: dict[str, str]) -> None:
        """Increment the terminal model-call counter for the current UTC day."""
        self.record_counter(MODEL_ROUTE_METRIC, dimensions, resource)

    def record_client_active(self, resource: dict[str, str]) -> bool:
        """Record this install at most once in any rolling 24-hour window."""
        return self._record_once_per_interval(
            _ACTIVE_INSTALL_STATE_KEY, CLIENT_ACTIVE_METRIC, {}, resource
        )

    def record_install_snapshot(self, dimensions: dict[str, str], resource: dict[str, str]) -> bool:
        """Record the configuration snapshot at most once in any rolling 24-hour window."""
        return self._record_once_per_interval(
            _INSTALL_SNAPSHOT_STATE_KEY, INSTALL_SNAPSHOT_METRIC, dimensions, resource
        )

    def recorded_milestones(self) -> frozenset[str]:
        return self._latched(_MILESTONE_STATE_PREFIX)

    def record_milestone(self, milestone: str, install_age_bucket: str, resource: dict[str, str]) -> bool:
        """Record an install milestone at most once, ever (compare-and-set across processes)."""
        dimensions = {"install_age_bucket": install_age_bucket, "milestone": milestone}
        return self._record_once_ever(f"{_MILESTONE_STATE_PREFIX}{milestone}", MILESTONE_METRIC, dimensions, resource)

    def recorded_features(self) -> frozenset[str]:
        return self._latched(_FEATURE_STATE_PREFIX)

    def record_feature_adoption(self, feature: str, days_bucket: str, resource: dict[str, str]) -> bool:
        """Record a feature's first use at most once per install, ever (same latch as milestones)."""
        dimensions = {"days_since_install_bucket": days_bucket, "feature": feature}
        return self._record_once_ever(f"{_FEATURE_STATE_PREFIX}{feature}", FEATURE_ADOPTION_METRIC, dimensions, resource)

    @staticmethod
    def _validate_counter(
        metric_name: str, dimensions: dict[str, str], resource: dict[str, str]
    ) -> None:
        if metric_name not in COUNTER_METRICS:
            raise ValueError(f"Unsupported shared metric: {metric_name}")
        if not counter_dimensions_are_valid(metric_name, dimensions):
            raise ValueError(f"Unsupported dimensions for shared metric: {metric_name}")
        if not client_resource_is_valid(resource):
            raise ValueError("Unsupported shared-metrics client resource")

    @staticmethod
    def _parse_state_timestamp(value: Any) -> datetime | None:
        try:
            parsed = datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return None
        return None if parsed.tzinfo is None else parsed.astimezone(UTC)

    @classmethod
    def _package_metrics(cls, rows: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
        """Package rows, merging rows a re-bucket folded onto the same dimensions into one metric."""
        merged: dict[tuple[str, str], dict[str, Any]] = {}
        for row in rows:
            metric = cls._package_metric(row)
            if metric is None:
                continue
            key = (metric["name"], _compact_json(metric["dimensions"]))
            if key in merged:
                merged[key]["value"] += metric["value"]
            else:
                merged[key] = metric
        return list(merged.values())

    @staticmethod
    def _package_metric(row: Mapping[str, Any]) -> dict[str, Any] | None:
        metric_name = str(row["metric_name"])
        dimensions = json.loads(row["dimensions_json"])
        # An unknown field set is tamper evidence and fails closed (must-not-be-exported). A known
        # shape whose values fell out of the contract was recorded by an earlier build or catalog
        # (#133017): re-bucket it inside the closed enum, or leave the row out when its field has no
        # bucket, rather than abort the whole period's package. Either way no stale value leaves.
        if not isinstance(dimensions, dict) or not counter_dimensions_shape_is_known(metric_name, dimensions):
            raise ValueError(f"Unsupported dimensions for shared metric: {metric_name}")
        if not counter_dimensions_are_valid(metric_name, dimensions):
            conformed = conform_counter_dimensions(metric_name, dimensions)
            if conformed is None:
                logger.info("Shared-metric %s row holds a retired value with no bucket; not packaged", metric_name)
                return None
            logger.info(
                "Shared-metric %s row drifted out of the contract since it was recorded; "
                "packaged with bucketed dimensions %s", metric_name, _compact_json(conformed),
            )
            dimensions = conformed
        return {
            "name": metric_name, "type": "counter", "dimensions": dimensions,
            "value": row["value"] - row["packaged_value"],
        }
