"""Carrier-aware user-turn rewind (``/undo``, ``/retry``) — the ONE implementation behind the CLI, the
gateway and the TUI. Rewind is a persisted-history operation: the durable transcript is the authority,
the warm (in-memory) history only has to agree with it. A composite compaction carrier (retained
summary + live human ask in one row) keeps its hidden handoff scaffold as the new head."""

from __future__ import annotations
from hermes_db.domains.sessions.rewind import RewindOutcome, RewindPlan, RewindTargetUnavailableError, _HISTORY_CHANGED, _comparison_content, _user_indices, plan_user_turn_rewind, rewind_user_turn

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


logger = logging.getLogger("hermes")


def retain_refused_turn_for_display(
    session_db: Any, session_id: Any, *, notice: str, boundary_row_id: Optional[int] = None,
) -> bool:
    """Owner-side durable retention of a just-safety-refused turn, for surfaces that own a direct
    ``SessionDB`` (CLI, ACP). The agent flushed the turn-start user row before the refusal was known,
    so a clean in-memory history alone would still let a ``/resume`` or a fresh session load re-send
    the blocked content and re-lock the chat. Take that whole turn (the user row, any tool rounds that
    ran, and the refusal) out of the MODEL context — exactly as ``/undo`` does — while KEEPING the
    user's own message visible in the chat SURFACES: it is retained in the display projection and
    tagged as a refused notice (``SessionDB.retain_refused_turn_for_display``). The managed-worker
    (Bot Chat) path retains owner-side through its async store instead. Best-effort: a refusal must
    never crash turn teardown, and if retention fails the user still has the live refusal notice.
    Returns True when a turn was retained.

    ``boundary_row_id`` (when the refusal handler captured it) is the durable row id that STARTED the
    refused run — the precise rewind target. Without it the retention guesses the newest user turn,
    which is the wrong row when a mid-turn steer appended a newer user row, or when the refused input
    was a hidden/internal (non-user-originated) row (``#149708`` review).

    This lives OUTSIDE the agent core on purpose: it is an OWNER-side operation (the owner holds a
    direct, mutable transcript), never a call the worker agent makes on its ``RuntimeSessionStore``.
    """
    if session_db is None or not session_id:
        return False
    try:
        return bool(session_db.retain_refused_turn_for_display(
            session_id, notice=notice, boundary_row_id=boundary_row_id))
    except Exception:  # best-effort; a refusal must never crash turn teardown
        logger.warning(
            "content-policy refusal: could not retain the refused turn for %s", session_id, exc_info=True)
        return False












class SessionRewindMixin:
    """``SessionDB`` mixin: soft-delete from one user turn onward, validated against the warm history."""

    def retain_refused_turn_for_display(
        self, session_id: str, *, notice: str, boundary_row_id: Optional[int] = None,
    ) -> bool:
        """Retain a just-safety-refused turn for DISPLAY only, excluded from the MODEL. The whole
        turn leaves the active model context exactly as ``/undo``'s soft-delete does — so the
        deterministic safety filter can't re-trip and lock the chat — but the user's own message
        stays visible: its row is kept in the display projection (``compacted = 1``, the same way
        compaction-archived rows remain visible) and tagged ``content_refused`` with *notice*, while
        any tool rounds + the refusal collapse out of display (they stay soft-deleted / removed). The
        user keeps SEEING "you asked X → refused, try a different query"; the model sees none of it
        (``active = 0``). Returns True when a turn was retained, False when there was nothing to
        retain.

        ``boundary_row_id`` is the durable row that STARTED the refused run (captured by the refusal
        handler). It is the precise target: the NEWEST user turn is the wrong row when a mid-turn
        steer appended a later user row (``-1`` drops only the steer, leaving the original ask + its
        tool rounds live in the model) or when the refused input is a hidden/internal, non-user-
        originated row (``-1`` would drop a PRIOR accepted turn). Only when no boundary was handed in
        does this fall back to the newest user turn (best-effort).

        OWNER-side only (CLI/ACP direct store, and the gateway's async store); never a worker call.
        """
        from agent.turn_failure_copy import CONTENT_REFUSED_DISPLAY_KIND, CONTENT_REFUSED_METADATA_KEY
        plan = self._plan_refused_retention(session_id, boundary_row_id)
        if plan is None:
            return False
        target_row_id, preserve_handoff, expected_active_ids = plan

        # ONE write transaction for BOTH sides: a crash between the model-side soft-delete and the
        # display re-surface would otherwise drop the user's message from BOTH views with no restart
        # path (half-applied retention). ``rewind_in_transaction`` soft-deletes the whole turn
        # (archiving a composite carrier's handoff as the new active head when the refused turn head
        # is one), then the SAME txn re-surfaces the target row into the display projection tagged
        # ``content_refused``: ``compacted = 1`` keeps it shown the way compaction-archived rows are,
        # ``active`` stays 0 so the model never sees it again.
        def _do(conn) -> bool:
            from hermes_state_mutation_transcript import rewind_in_transaction
            rewind_in_transaction(
                self, conn, session_id, target_row_id,
                preserve_compaction_handoff=preserve_handoff,
                expected_active_ids=expected_active_ids)
            row = conn.execute(
                "SELECT display_metadata FROM messages WHERE id = ? AND session_id = ?",
                (target_row_id, session_id)).fetchone()
            if row is None:
                return False
            meta = self._decode_display_metadata(row["display_metadata"]) or {}
            meta[CONTENT_REFUSED_METADATA_KEY] = {"notice": notice}
            conn.execute(
                "UPDATE messages SET compacted = 1, display_kind = ?, display_metadata = ? "
                "WHERE id = ? AND session_id = ?",
                (CONTENT_REFUSED_DISPLAY_KIND, self._encode_display_metadata(meta),
                 target_row_id, session_id))
            return True

        return bool(self._execute_write(_do))

    def _plan_refused_retention(self, session_id: str, boundary_row_id: Optional[int]):
        """``(target_row_id, preserve_compaction_handoff, expected_active_ids)`` for the rewind that
        retains the refused turn, or ``None`` when there is nothing to retain.

        Targets ``boundary_row_id`` (the refused run's original durable boundary) when it resolves to
        an active ``user`` row — robust to a mid-turn steer appending a newer user row and to a hidden
        /internal refused input that the newest-user-turn guess would skip. The active-id pin alone
        guards concurrency (if the whole active set is unchanged, so is the target), so the content
        pin ``rewind_user_turn`` needs is unnecessary here. Falls back to the newest user turn when no
        usable boundary was supplied.
        """
        from agent.context_compressor import split_user_originated_turn
        if isinstance(boundary_row_id, int) and boundary_row_id > 0:
            with self._read_ctx() as conn:
                row = conn.execute(
                    "SELECT role, active, content, display_metadata FROM messages "
                    "WHERE id = ? AND session_id = ?", (boundary_row_id, session_id)).fetchone()
            if row is not None and row["role"] == "user" and row["active"]:
                decoded = {"role": "user", "content": self._decode_content(row["content"]),
                           "display_metadata": self._decode_display_metadata(row["display_metadata"])}
                handoff, _live_view = split_user_originated_turn(decoded)
                return boundary_row_id, handoff is not None, self.get_active_message_ids(session_id)
            # The boundary vanished, was already rewound, or is not a rewindable user row: fall
            # through to the newest-user-turn best effort rather than failing the retention.
        try:
            plan = self.plan_user_turn_rewind(session_id, -1)
        except RewindTargetUnavailableError:
            return None
        return plan.target_row_id, plan.scaffold is not None, plan.expected_active_ids

    def rewind_user_turn(self, session_id: str, user_ordinal: int, *, warm_history: Optional[list[dict[str, Any]]]=None, require_retryable: bool=False, require_composite: bool=False, adopt_row_ids: bool=False) -> RewindOutcome:
        """Rewind the active transcript to just before user turn ``user_ordinal`` (0 = oldest; negative counts
            back from the newest and clamps to the oldest, so ``-n`` is ``/undo n``). ``warm_history`` (CLI/TUI):
            the in-memory view must have the same user turns and the same live target text as the durable
            transcript, else ``RuntimeError`` and nothing changes; its (richer) prefix is what gets installed.
            ``require_retryable``: the live payload must be losslessly replayable as text (``ValueError`` from
            :func:`retryable_user_text` before any write). ``require_composite``: the target must be a compaction
            carrier. ``adopt_row_ids`` (TUI): copy durable ``_row_id`` identities onto the installed warm prefix so
            clients can address follow-ups by row; the CLI leaves its history shape alone. Out-of-range /
            wrong-shape targets raise :class:`RewindTargetUnavailableError`."""
        return rewind_user_turn(self.plan_user_turn_rewind, self.rewind_to_message, session_id, user_ordinal, warm_history=warm_history, require_retryable=require_retryable, require_composite=require_composite, adopt_row_ids=adopt_row_ids)

    def plan_user_turn_rewind(self, session_id: str, user_ordinal: int, *, warm_history: Optional[list[dict[str, Any]]]=None, require_retryable: bool=False, require_composite: bool=False) -> RewindPlan:
        """Every read and check :meth:`rewind_user_turn` makes before its write, with no write: the
            gateway ``/retry`` commits the planned rewind inside its re-send's admission transaction
            (``rewind_in_transaction`` with the plan's pins), so a refused re-send leaves it unapplied."""
        return plan_user_turn_rewind(self.get_messages_as_conversation, self.get_active_message_ids, session_id, user_ordinal, warm_history=warm_history, require_retryable=require_retryable, require_composite=require_composite)
