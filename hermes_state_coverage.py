"""Held-row coverage resolution for in-place compaction: which durable rows the compressor actually held.

Names carried-forward dicts, id-less held dicts and the rows an alternation repair merged, dropped or
folded, so ``archive_and_compact`` archives exactly those (or falls back to the watermark when a durable
held row cannot be named). Mixin bound via the MRO next to SessionMessagesMixin, which owns the writes.
"""

from __future__ import annotations

from hermes_db.domains.sessions.coverage import CoverageRules, _text_of, _holds_as_block, _images_replaced

from collections import Counter
from typing import Any, Dict, List, Optional, Set, Tuple

from agent.message_metadata import DB_ROW_SNAPSHOT, MESSAGE_UID, message_uid_or_none
from hermes_cli.timefmt import coerce_epoch
from hermes_state_common import _id_chunks, _placeholders
from hermes_db.domains.sessions.codec import _parse_tool_calls


class SessionCoverageMixin(CoverageRules):
    """Coverage helpers for SessionDB; relies on SessionMessagesMixin's codec/identity helpers."""

    def _carried_tail_ids(
        self, conn, tail_ids: list[int], compacted_messages: list[dict[str, Any]],
    ) -> tuple[dict[int, int], set[int]]:
        """Rows of *tail_ids* that *compacted_messages* already carry -> ``({row id: carrying dict index}, weak)``.

        A row above the watermark is normally a concurrent append the summary never saw, so the commit
        clones it after the compacted set. A row the compressor ALSO held (flushed after the watermark
        was read, or left unnamed so coverage fell back to the watermark) is already in the compacted
        set as a carried copy; cloning it too stores the message twice, with a fresh id and timestamp
        each (#137197). A claim must prove the occurrence AND the version, so the next request sees exactly
        what it would have seen with the clone minus the second copy: only a dict that names the row
        (``_row_id``, else ``message_uid``) may claim it, never matching text, which another surface can
        append independently. The first pass claims a named dict holding the row's stored content and its
        replayed sidecars (``_replays_as``). The second lets a still-unclaimed named dict with other content
        claim the row only when the compressor's own rewrite of the row's CURRENT version explains the
        difference (see ``_rewrite_explains``), exactly one tail row carries that uid and no active row
        outside *tail_ids* does (there the dict's original is that row, so the tail row is another version).
        Anything else is cloned: a duplicate, never a stale or missing model input. Each dict claims at most
        one row and each row is claimed once.

        ``weak`` holds the rows claimed by a rewritten carry: it is not the stored text, so the caller archives
        those as compacted history, never rewinds them out of display.
        """
        if not tail_ids or not compacted_messages:
            return {}, set()
        by_row, by_uid = self._index_held_dicts(compacted_messages)
        rows = conn.execute(
            # Every column: the claims compare replayed sidecars and the row's version digest (DB_ROW_SNAPSHOT).
            f"SELECT * FROM messages WHERE id IN ({_placeholders(tail_ids)}) ORDER BY id", tail_ids,
        ).fetchall()
        carried: dict[int, int] = {}
        for row in rows:
            index = self._claim_stored_copy(row, compacted_messages, by_row, by_uid, set(carried.values()))
            if index is not None:
                carried[int(row["id"])] = index
        named_uids = {*by_uid, *(named[2] for named in by_row.values() if named[2] is not None)}
        held_elsewhere = self._uids_active_outside(conn, rows, tail_ids, named_uids)
        tail_uids = Counter(row[MESSAGE_UID] for row in rows if row[MESSAGE_UID])
        weak: set[int] = set()
        for row in rows:
            row_id, row_uid = int(row["id"]), row[MESSAGE_UID] or None
            if row_id in carried or row_uid is None or tail_uids[row_uid] != 1 or row_uid in held_elsewhere:
                continue
            index = self._rewritten_carry(row, row_uid, compacted_messages, by_row, by_uid, set(carried.values()))
            if index is not None:
                carried[row_id] = index
                weak.add(row_id)
        return carried, weak


    @staticmethod
    def _uids_active_outside(conn, rows, tail_ids: list[int], named_uids) -> set[str]:
        """uids of tail *rows* a held dict names that an ACTIVE row outside *tail_ids* (a covered row, below the
        watermark) also carries: there the dict's own original is that row, so the tail row is another version."""
        wanted = sorted({row[MESSAGE_UID] for row in rows if row[MESSAGE_UID] in named_uids})
        if not wanted:
            return set()
        tail, session_id = set(tail_ids), rows[0]["session_id"]
        return {
            found[MESSAGE_UID]
            for chunk in _id_chunks(wanted)
            for found in conn.execute(
                f"SELECT id, {MESSAGE_UID} FROM messages WHERE session_id = ? AND active = 1 "
                f"AND {MESSAGE_UID} IN ({_placeholders(chunk)})", (session_id, *chunk)).fetchall()
            if int(found["id"]) not in tail
        }


    def _resolve_carried_row_ids(
        self, conn, session_id: str, carried_messages: list[dict[str, Any]],
    ) -> list[int]:
        """Resolve byte-identical carried-forward live dicts to their ACTIVE durable originals.

        _row_id is authoritative when the message carries it and the stored identity still matches.
        Resume surfaces that intentionally omit row ids fall back to a UNIQUE
        (role/content/tool identity, timestamp) match. Ambiguous or timestamp-less fallbacks are left
        as compacted history rather than risking a false rewind classification.
        """
        if not carried_messages:
            return []
        carried: list[tuple[tuple[Any, ...], Any, Any]] = []
        for message in carried_messages:
            if not isinstance(message, dict):
                continue
            identity = self._row_identity(
                message.get("role", "unknown"), message.get("content"), message.get("tool_call_id"),
                _parse_tool_calls(message.get("tool_calls")))
            row_id = message.get("_row_id")
            if not (isinstance(row_id, int) and not isinstance(row_id, bool) and row_id > 0):
                row_id = None
            carried.append((identity, row_id, message.get("timestamp")))

        def _index(ids: Optional[list[int]]):
            by_id: dict[int, tuple[Any, ...]] = {}
            by_key: dict[tuple[Any, ...], list[int]] = {}
            narrow = f" AND id IN ({_placeholders(ids)})" if ids else ""
            for row in conn.execute(
                "SELECT id, role, content, tool_call_id, tool_calls, timestamp FROM messages "
                f"WHERE session_id = ? AND active = 1{narrow} ORDER BY id",
                (session_id, *(ids or ())),
            ).fetchall():
                rid = int(row["id"])
                by_id[rid] = self._row_identity(
                    row["role"], self._decode_content(row["content"]), row["tool_call_id"],
                    _parse_tool_calls(row["tool_calls"]))
                ts = coerce_epoch(row["timestamp"], field="message timestamp")
                if ts is not None:
                    by_key.setdefault((*by_id[rid], ts), []).append(rid)
            return by_id, by_key

        # The common micro pass carries dicts that all hold a matching _row_id, so the identity
        # check only needs those rows; a full active-row scan is reserved for the fallbacks.
        row_ids = [row_id for _, row_id, _ in carried if row_id is not None]
        by_id, by_key = _index(row_ids if len(row_ids) == len(carried) else None)
        if len(row_ids) == len(carried) and any(by_id.get(rid) != ident for ident, rid, _ in carried):
            by_id, by_key = _index(None)

        resolved: list[int] = []
        for identity, row_id, raw_timestamp in carried:
            if row_id is not None and by_id.get(row_id) == identity:
                resolved.append(row_id)
                continue
            timestamp = coerce_epoch(raw_timestamp, field="message timestamp")
            if timestamp is None:
                continue
            matches = by_key.get((*identity, timestamp), [])
            if len(matches) == 1:
                resolved.append(matches[0])
        return list(dict.fromkeys(resolved))

    def _matching_active_ids(self, conn, session_id: str, message: dict[str, Any]) -> list[int]:
        """Active row ids whose stored role and content equal *message*. Empty when it was never persisted."""
        content = message.get("content")
        if not isinstance(content, str):
            return []
        stored = self._encode_content(self._loaded_view_content(message.get("role", "unknown"), content))
        return [int(row["id"]) for row in conn.execute(
            "SELECT id FROM messages WHERE session_id = ? AND active = 1 AND role = ? AND content = ?",
            (session_id, message.get("role"), stored)).fetchall()]

    def _matching_retired_ids(
        self, conn, session_id: str, retired: dict[str, Any], watermark: Optional[int] = None,
    ) -> list[int]:
        """Active rows equal to a row the alternation repair retired without an id.

        Matched on role, loaded-view content (an empty assistant stores ``None`` or ``""``), tool_call_id
        and the ids of its tool calls. Only rows at or below *watermark*: the repair ran on a load taken
        before the snapshot, so a later equal row is another surface's append.
        """
        role = str(retired.get("role") or "")
        bound = watermark is not None
        rows = conn.execute(
            "SELECT id, content, tool_call_id, tool_calls FROM messages WHERE session_id = ? AND active = 1 "
            f"AND role = ?{' AND id <= ?' if bound else ''} ORDER BY id",
            (session_id, role, *((int(watermark),) if bound else ()))).fetchall()
        want_calls = list(retired.get("tool_call_ids") or ())
        matches = []
        for row in rows:
            content = self._loaded_view_content(role, self._decode_content(row["content"]))
            if (content or None) != (retired.get("content") or None):
                continue
            if (row["tool_call_id"] or None) != (retired.get("tool_call_id") or None):
                continue
            calls = _parse_tool_calls(row["tool_calls"]) or []
            ids = [call.get("id") for call in calls if isinstance(call, dict)] if isinstance(calls, list) else []
            if ids != want_calls:
                continue
            matches.append(int(row["id"]))
        return matches

    def _merged_user_run(
        self, conn, session_id: str, message: dict[str, Any], watermark: Optional[int] = None,
    ) -> Optional[list[int]]:
        """Active rows an alternation repair merged into *message*: ``[]`` for none, None when ambiguous.

        A reload without row ids turns a durable ``user;user`` pair (a prompt that never got its reply)
        into one dict equal to neither row. Read as an unpersisted turn, its rows would be re-sequenced
        after the compacted set like concurrent appends, behind the turn that is running.
        Only a dict the repair stamped: a prompt that was never persisted can carry the same text as
        rows another surface appended, and those were never held.
        Only rows at or below *watermark*: the repair ran on a load taken before the snapshot, so a
        run appended later that joins to the same text is another surface's, not the merged one.
        """
        from agent.conversation_compression_archive import MERGED_DURABLE_ROWS, OWN_ROW, RETIRED_DURABLE_ROWS

        content, width = message.get("content"), message.get(MERGED_DURABLE_ROWS)
        if message.get("role") != "user" or not isinstance(content, str) or type(width) is not int or width < 2:
            return []
        from gateway.message_timestamps import strip_leading_message_timestamps

        content, _ = strip_leading_message_timestamps(content)
        bound = watermark is not None
        rows = [
            (int(row["id"]), row["role"], self._loaded_view_content(row["role"], self._decode_content(row["content"])))
            for row in conn.execute(
                f"SELECT id, role, content FROM messages WHERE session_id = ? AND active = 1"
                f"{' AND id <= ?' if bound else ''} ORDER BY id",
                (session_id, *((int(watermark),) if bound else ()))).fetchall()]
        # Dropping an orphan can make user rows adjacent only in the repaired view.
        # Skip only uniquely proved retired originals, never arbitrary intervening rows.
        retired_ids = set()
        for retired in message.get(RETIRED_DURABLE_ROWS) or ():
            if retired.get(OWN_ROW):
                continue
            matches = self._matching_retired_ids(conn, session_id, retired, watermark)
            if len(matches) != 1:
                return None
            retired_ids.update(matches)
        rows = [row for row in rows if row[0] not in retired_ids]
        runs: list[list[int]] = []
        for start in range(len(rows)):
            merged = ""
            for end in range(start, len(rows)):
                _row_id, role, part = rows[end]
                if role != "user" or not isinstance(part, str):
                    break
                merged = f"{merged}\n\n{part}" if merged and part else (merged or part)
                if not content.startswith(merged):
                    break
                if end - start + 1 == width:
                    if merged == content:
                        runs.append([rows[i][0] for i in range(start, end + 1)])
                    break
        if len(runs) > 1:
            return None
        return runs[0] if runs else []
