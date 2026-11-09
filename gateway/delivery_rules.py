"""Pure delivery recovery policy shared by SQLite and PostgreSQL ledgers."""
from __future__ import annotations
import re
from typing import Any, Optional

_DEAD_ERROR_KINDS = frozenset({"forbidden", "not_found"})

def classify_dead_error(error_text: Optional[str]) -> Optional[str]:
    """Best-effort dead-target error_kind from a raised error's text, else None. ``_deliver_to_platform``
    raises on hard failure (no SendResult), so ``deliver()`` only has the exception string. ``not_found``
    collapses chat-level and thread/topic/message-level failures: only a whole-chat not_found means the
    target is dead — a deleted forum topic or edited-away message must not mark the entire chat dead."""
    if not error_text:
        return None
    try:
        from gateway.platforms.base import classify_send_error, is_chat_level_not_found
    except Exception:  # pragma: no cover - import guard
        return None
    kind = classify_send_error(None, error_text=error_text)
    dead = kind in _DEAD_ERROR_KINDS and (kind != "not_found" or is_chat_level_not_found(error_text=error_text))
    return kind if dead else None

# Redelivery policy knobs (deliberately not config — the ledger is gated by
# ``gateway.delivery_ledger`` and these only matter in the rare recovery path).
MAX_ATTEMPTS = 3
STALE_AFTER_SECONDS = 24 * 60 * 60
_RETENTION_SECONDS = 7 * 24 * 60 * 60
_MAX_ROWS = 500

# Visible prefixes for redeliveries that might duplicate an already-received message (crash mid-send /
# post-rejection retry) — honest at-least-once. Runtime recovery uses a distinct marker: no restart
# occurred, but a network rejection's acknowledgement can still have been lost independently.
RECOVERED_MARKER = "♻️ Recovered reply — the gateway restarted during delivery, so this may be a duplicate:\n\n"
RECONNECTED_MARKER = ("♻️ Recovered reply — the messaging platform reconnected after the original "
                      "delivery failed, so this may be a duplicate:\n\n")
# A reply refused by flood control may have gone out as several requests (the adapter chunks long replies,
# and MarkdownV2 escaping alone can push a reply that fits one message into two), and the platform may have
# accepted the first chunk(s) before refusing the rest; the send result does not say which landed. The raw
# length of the stored text says nothing about that, so every flood redelivery carries a marker, and neither
# of the markers above tells the truth here (no restart, no reconnect): the rate limit gets its own.
FLOOD_MARKER = ("♻️ Recovered reply — the messaging platform's rate limit refused the original, so part of "
                "it may already have arrived above:\n\n")

# Errors whose send contract proves the platform never saw the request: retried as soon as the adapter
# is back, no backoff. Every other rejection is retried too (#91653: a 5xx or a transient parse error
# used to strand the reply in ``failed`` until the next restart), but only after a backoff that grows
# with the attempts already spent, so a platform-side outage is not hammered by the redelivery timer.
# A whole-chat death (blocked bot, deleted group, deactivated user) is never retried: the target is gone.
_RUNTIME_RETRYABLE_ERRORS = frozenset({"send_path_degraded"})
# One tier per in-process retry; the last budgeted attempt is left to the boot sweep (retry_not_before).
_RETRY_BACKOFF_SECONDS = (30.0, 120.0)
assert len(_RETRY_BACKOFF_SECONDS) == MAX_ATTEMPTS - 1

# A final send the platform refused with flood control is the other transient case: a 429 means the
# refused request was never accepted, and the platform said how long to wait. Adapters fail such sends
# closed as ``flood_control:<seconds>`` on purpose (#91969) so that this ledger owns the wait instead of
# the send coroutine sleeping through it. Before this the row simply sat in ``failed`` until the next
# restart's sweep, which then redelivered it hours late under the "gateway restarted during delivery"
# marker.
FLOOD_ERROR_PREFIX = "flood_control:"
FLOOD_RETRY_DEFAULT_SECONDS = 60.0
FLOOD_RETRY_CAP_SECONDS = 15 * 60.0
FLOOD_RETRY_SLACK_SECONDS = 2.0

# The canonical prefix above is what the adapters produce for a flood they decide not to sleep. It is
# not the only shape that reaches this ledger. PTB raises ``RetryAfter``, whose own text reads
# "Flood control exceeded. Retry in 185 seconds", and that text is what lands in ``last_error``
# whenever a send fails on a path that has not been normalized, or was written by an older build
# before it was. Such a row has to be recognised too: unrecognised, it is treated as an ordinary
# failure, so no redelivery timer is armed for it and a boot sweep claims it immediately instead of
# adopting it until its deadline, spending the one attempt inside the penalty that caused it.
# Matching requires the "flood control" wording as well as the delay, so an unrelated error that
# merely suggests retrying is never mistaken for a flood.
_RAW_FLOOD_RE = re.compile(r"flood control exceeded.*?retry in\s+(\d+(?:\.\d+)?)", re.IGNORECASE)


def _raw_flood_wait(text: str) -> Optional[float]:
    """Seconds asked for by a flood error still carrying the platform's own wording, else ``None``."""
    match = _RAW_FLOOD_RE.search(text or "")
    if not match:
        return None
    try:
        return float(match.group(1))
    except (TypeError, ValueError):
        return None


def is_reconnect_only(error: Any) -> bool:
    """True for a row that only an adapter reconnect may retry (no timer, no backoff)."""
    return str(error or "").strip().lower() in _RUNTIME_RETRYABLE_ERRORS


def is_flood_error(error: Any) -> bool:
    """True for a flood refusal: the adapters' fail-closed ``flood_control:<seconds>`` result, or a
    row still carrying the platform's own flood wording (see ``_RAW_FLOOD_RE``)."""
    text = str(error or "").strip().lower()
    return text.startswith(FLOOD_ERROR_PREFIX) or _raw_flood_wait(text) is not None


def flood_wait_seconds(error: Any, default: float = FLOOD_RETRY_DEFAULT_SECONDS) -> float:
    """The wait the platform asked for, read from ``flood_control:<seconds>``; ``default`` when unreadable."""
    text = str(error or "").strip().lower()
    wait = default
    if text.startswith(FLOOD_ERROR_PREFIX):
        try:
            wait = float(text[len(FLOOD_ERROR_PREFIX):].strip())
        except ValueError:
            wait = default
    else:
        # A row still carrying the platform's own flood wording states its delay just as precisely,
        # and the deadline must use it rather than the generic default.
        raw = _raw_flood_wait(text)
        if raw is not None:
            wait = raw
    return wait if wait > 0 else default


def flood_retry_delay(seconds: Any) -> float:
    """How long a redelivery timer sleeps for a wait of ``seconds``: capped so a huge or bogus value cannot
    park the timer for hours (the row's own deadline, not the timer, decides eligibility when it fires),
    plus a little slack so the timer lands after the deadline rather than on it."""
    try:
        wait = float(seconds)
    except (TypeError, ValueError):
        wait = FLOOD_RETRY_DEFAULT_SECONDS
    return min(max(wait, 0.0), FLOOD_RETRY_CAP_SECONDS) + FLOOD_RETRY_SLACK_SECONDS


def _failed_stamp(updated_at: Any) -> float:
    try:
        return float(updated_at or 0.0)
    except (TypeError, ValueError):
        return 0.0


def flood_not_before(updated_at: Any, last_error: Any) -> float:
    """Earliest moment a flood-refused row may be resent: the refusal's timestamp (``mark_failed`` sets
    ``updated_at``) plus the platform's wait. Enforced by the sweeps so neither an early timer nor a
    reconnect sweep spends a redelivery attempt inside the penalty window."""
    return _failed_stamp(updated_at) + flood_wait_seconds(last_error)


def retry_not_before(updated_at: Any, last_error: Any, attempts: Any) -> Optional[float]:
    """Earliest moment a failed row may be resent, or ``None`` for a row the runtime must leave alone:
    a flood refusal keeps the platform's own wait, an allowlisted reconnect error is due at once, a
    whole-chat death is final, and any other rejection backs off by the attempts already spent — but
    never spends the LAST budgeted attempt. An unclassified outage can outlast any timer, and a row
    the timer abandoned would be lost for good; leaving one attempt keeps it recoverable by the boot
    sweep after a restart, which is a real recovery signal."""
    if is_flood_error(last_error):
        return flood_not_before(updated_at, last_error)
    text = str(last_error or "").strip().lower()
    if is_reconnect_only(text):
        return _failed_stamp(updated_at)
    if classify_dead_error(text):
        return None
    spent = int(attempts or 0)
    if spent >= MAX_ATTEMPTS - 1:
        return None
    return _failed_stamp(updated_at) + _RETRY_BACKOFF_SECONDS[spent]



def _claimed_row(oid, session_key, platform, chat_id, thread_id, content, attempts, profile, *,
                 needs_marker: bool, runtime: bool = False, flood: bool = False,
                 last_error: Optional[str] = None) -> dict[str, Any]:
    """Claimed-row dict handed back for redelivery. A marked row names its own cause: ``flood`` (a reply
    the rate limit refused, possibly after accepting part of it) gets FLOOD_MARKER at boot or at runtime, a
    ``runtime`` reconnect replay gets RECONNECTED_MARKER, and a boot-recovered crash keeps the runner's
    restart marker default. ``last_error`` is the row's pre-claim error, carried so a runtime claim that is
    released unsent goes back to ``failed`` with the same error and keeps its retry eligibility."""
    marker = FLOOD_MARKER if flood else (RECONNECTED_MARKER if runtime else None)
    return {"obligation_id": oid, "session_key": session_key, "platform": platform, "chat_id": chat_id,
            "thread_id": thread_id, "content": content, "needs_marker": needs_marker,
            **({"marker": marker} if needs_marker and marker else {}), "profile": profile,
            **({"runtime_recovery": True} if runtime else {}),
            **({"last_error": last_error} if last_error else {}), "attempts": attempts + 1}
