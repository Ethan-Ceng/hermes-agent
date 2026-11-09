"""Bounded replay context for committed authority changes, never election proof.

Reused from the recovery prerequisite; lineage mechanics build on Teknium's
#99047, authored commit 6af548a1f73f26bca54dd2e23f0d278c37f3ba6c.
The passive wire contract applies stricter bounds in hosted_room_passive_lineage.
"""

from __future__ import annotations
from hermes_db.domains.rooms.authority_rules import AuthorityHistoryError, AuthoritySpan, MAX_AUTHORITY_SPANS, TRANSFER_KINDS, at_sequence, history_from_rows, validate_history

import json
from dataclasses import dataclass
from typing import Any

from hermes_db.domains.rooms.rules import identifier

#: Committed authority transfers, each the first event of its span. ``authority.claimed`` is the new
#: owner's record; ``authority.lost`` is the record the outgoing owner commits when it is fenced to
#: a proven newer epoch (``hosted_room_replicas.demote_room``; the standalone -> gateway handoff in
#: ``hosted_rooms_gateway_import``). Both carry the same previous/next/epoch payload and are
#: checked alike, so a store whose log holds its own fence followed by a later claim (a handed-off
#: room, a returning gateway that reclaims) reads as one unbroken chain.












def origin_gateway_id(room: dict[str, Any]) -> str:
    """Keep the group/session namespace stable when its coordinator changes."""
    history = validate_history(room.get("authority_history"), gateway_id=room["authority_gateway_id"],
                               epoch=room["authority_epoch"])
    return history[0].gateway_id


def read_history_locked(conn, room_id: str, *, gateway_id: str, epoch: int) -> list[dict[str, Any]] | None:
    """Read committed authority transfers within the caller's room-state transaction.

    Legacy adoption is left on its existing path; it is not retroactively
    certified as a history of physical-host transfers.
    """
    rows = conn.execute(
        f"""SELECT seq,authority_epoch,actor_json,payload_json FROM hosted_room_events
           WHERE room_id=? AND kind IN {TRANSFER_KINDS} ORDER BY seq LIMIT ?""",
        (room_id, MAX_AUTHORITY_SPANS),
    ).fetchall()
    return history_from_rows(rows, gateway_id=gateway_id, epoch=epoch)
