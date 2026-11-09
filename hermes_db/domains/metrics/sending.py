"""Shared HTTP transport and claim-driven metrics delivery lifecycle; no storage backend."""
from __future__ import annotations
import gzip
import json
import logging
import random
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, UTC
from agent.retry_utils import parse_retry_after_seconds
from hermes_db.domains.metrics.policy import _isoformat, _utc_now
logger = logging.getLogger("hermes_cli.observability.shared_metrics_sender")

REQUEST_TIMEOUT_SECONDS = 30

MAX_ATTEMPTS = 3

_BACKOFF_BASE_SECONDS = 1

_BACKOFF_FACTOR = 5

GZIP_THRESHOLD_BYTES = 4096

MAX_PACKAGES_PER_PASS = 20

_CLAIM_LEASE_SECONDS = 300

_FAILURE_BACKOFF_SECONDS = 15 * 60

_PERMANENT_STATUSES = frozenset({400, 413})

MAX_SEND_ATTEMPTS = 25

MAX_OBS_ADVANCE_SECONDS = 30 * 24 * 3600

def _parse_stamp(value: str) -> datetime:
    """Parse a stamp this module itself wrote (Z-suffixed ISO-8601, UTC)."""
    return datetime.fromisoformat(value).astimezone(UTC)

@dataclass(slots=True)
class _Response:
    status: int
    retry_after: str | None
    body: str

def _post(endpoint: str, payload: bytes, *, timeout: int) -> _Response:
    """POST one package. Raises on transport failure; never on HTTP status."""
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "hermes-agent-shared-metrics/1",
    }
    body = payload
    if len(payload) > GZIP_THRESHOLD_BYTES:
        # mtime=0 keeps two sends of one package byte-identical on the wire too.
        body = gzip.compress(payload, mtime=0)
        headers["Content-Encoding"] = "gzip"

    request = urllib.request.Request(endpoint, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return _Response(
                response.status,
                response.headers.get("Retry-After"),
                response.read(2048).decode("utf-8", "replace"),
            )
    except urllib.error.HTTPError as exc:
        # An HTTP error status is a normal contract outcome, not a failure.
        return _Response(
            exc.code,
            exc.headers.get("Retry-After") if exc.headers else None,
            exc.read(2048).decode("utf-8", "replace") if exc.fp else "",
        )

def _retry_after_seconds(value: str | None, default: int) -> int:
    seconds = parse_retry_after_seconds(value)
    if seconds is None:
        return default
    # Clamp so a bogus value cannot park a package for years, and never go below one second.
    return max(1, min(int(seconds), 86_400))

class MetricsTransport:

    def __init__(
        self,
        store,
        endpoint: str,
        *,
        post=_post,
        sleep=time.sleep,
        now=_utc_now,
        max_attempts: int = MAX_ATTEMPTS,
        consent_check=None,
        outcome_factory,
    ) -> None:
        self._outcome_factory = outcome_factory
        self._store = store
        self._endpoint = endpoint
        self._post = post
        self._sleep = sleep
        self._now = now
        self._max_attempts = max_attempts
        # Called before every package. None disables the check for callers that have
        # already established consent out of band (tests, E2E).
        self._consent_check = consent_check

    @staticmethod
    def _body(payload_json: str, transmitted_id: str) -> bytes:
        """Rebuild the exact bytes to send: deterministic json.dumps of the stored package
        with install_id from the frozen ``sent_install_id`` column (resends are byte-identical)."""
        payload = dict(json.loads(payload_json))
        payload["install_id"] = transmitted_id
        return json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")

    def _defer(
        self, package_id: str, delay_seconds: int, reason: str, *, token: str | None = None
    ) -> None:
        # Clamp to >= 1s so a past deadline can never make the row instantly re-eligible.
        retry_at = self._now().timestamp() + max(1, int(delay_seconds))
        self._mark(
            package_id,
            token=token,
            send_state="pending",
            next_attempt_at=_isoformat(datetime.fromtimestamp(retry_at, tz=UTC)),
            last_error=reason[:500],
        )

    def _send_one(self, package: dict) -> str:
        """Try one package. Returns 'sent', 'rejected', or 'deferred'.

        Delivery is at-least-once: renewal plus token-fenced writes close the claim->POST
        and settle-after-reclaim gaps, but a suspension MID-POST can still duplicate.
        """
        package_id = package["package_id"]
        token = package.get("claim_token")
        body = self._body(package["payload_json"], package["derived"])

        def defer(delay: int, reason: str) -> str:
            self._defer(package_id, delay, reason, token=token)
            return "deferred"

        for attempt in range(1, self._max_attempts + 1):
            # Renew before EVERY external POST so a lapsed claimant yields even before anyone
            # reclaims. The ingest key is minute-prefixed: duplicates are distinct objects.
            if not self._renew_claim(package_id, token):
                logger.info(
                    "Shared-metrics claim on %s superseded or expired; yielding", package_id
                )
                return "deferred"
            try:
                response = self._post(self._endpoint, body, timeout=REQUEST_TIMEOUT_SECONDS)
            except Exception as exc:  # transport failure: offline, DNS, TLS
                reason = f"{type(exc).__name__}: {exc}"
            else:
                if response.status == 202:
                    self._mark(
                        package_id, token=token, send_state="sent",
                        sent_at=_isoformat(self._now()), last_error=None,
                    )
                    return "sent"
                if response.status in _PERMANENT_STATUSES:
                    logger.warning(
                        "Telemetry package %s rejected with HTTP %s; not retrying",
                        package_id,
                        response.status,
                    )
                    self._mark(
                        package_id, token=token, send_state="rejected",
                        last_error=f"HTTP {response.status}: {response.body[:400]}",
                    )
                    return "rejected"
                if response.status == 429:
                    return defer(
                        _retry_after_seconds(response.retry_after, _FAILURE_BACKOFF_SECONDS),
                        "rate limited",
                    )
                # 5xx and anything unexpected: retryable.
                reason = f"HTTP {response.status}"
            if attempt >= self._max_attempts:
                return defer(_FAILURE_BACKOFF_SECONDS, reason)
            self._sleep(self._backoff(attempt))

        return defer(_FAILURE_BACKOFF_SECONDS, "attempts exhausted")

    @staticmethod
    def _backoff(attempt: int) -> float:
        """1s, 5s, 25s with full jitter."""
        return random.uniform(0, _BACKOFF_BASE_SECONDS * (_BACKOFF_FACTOR ** (attempt - 1)))

    def send_pending(self):
        """Run one bounded pass, one claim+send at a time, re-checking consent before each
        send so revoking `send` mid-pass stops the remainder. Never raises."""
        outcome = self._outcome_factory()
        seen: set[str] = set()

        for _ in range(MAX_PACKAGES_PER_PASS):
            if not self._still_consented():
                # Reconcile through the single consent writer so the window closes at its
                # last confirmed moment.
                logger.info("Shared-metrics sending disabled mid-pass; stopping")
                self._reconcile(send_enabled=False)
                break
            try:
                package = self._claim_next(self._now(), seen)
            except Exception:
                logger.warning("Unable to select shared-metrics packages", exc_info=True)
                break
            if package is None:
                break

            seen.add(package["package_id"])
            if package.get("skip"):
                # Unusable row already marked rejected during the claim.
                result = "rejected"
            else:
                try:
                    result = self._send_one(package)
                except Exception:
                    logger.warning("Unable to send shared-metrics package", exc_info=True)
                    result = "deferred"
            setattr(outcome, result, getattr(outcome, result) + 1)
        return outcome

    def _still_consented(self) -> bool:
        """Re-read profile-owned send consent: docs promise ``send: false`` stops transmission
        immediately, and a pass can run for minutes."""
        if self._consent_check is None:
            return True
        try:
            return bool(self._consent_check())
        except Exception:
            # Fail CLOSED: if consent cannot be established, do not transmit.
            logger.warning("Unable to confirm shared-metrics send consent; stopping", exc_info=True)
            return False
