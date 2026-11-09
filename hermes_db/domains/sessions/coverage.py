"""Pure CoverageRules shared by native and PostgreSQL session persistence; no connections or storage lifecycle."""
from __future__ import annotations
from agent.message_metadata import DB_ROW_SNAPSHOT
from typing import Optional
from agent.message_metadata import message_uid_or_none
from hermes_db.domains.sessions.codec import _parse_tool_calls
from agent.message_metadata import MESSAGE_UID
from typing import Any

def _text_of(content: Any) -> str:
    """The text a message carries: a string, or its text parts joined; image parts carry none."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return '\n'.join(str(part.get('text') or '') for part in content if isinstance(part, dict) and part.get('type') in {'text', 'input_text', 'output_text'})
    return ''

def _holds_as_block(inner: str, outer: str) -> bool:
    """True when *inner* sits in *outer* as whole lines: the compressor adds only whole blocks around a carried
    row's text (header, markers, summary), so a hit that starts or ends mid-line is the row losing text instead.
    Blanks beside the hit count as line edges: the load lens strips the stored text, never the copy inside."""
    start = outer.find(inner)
    while start != -1:
        end = start + len(inner)
        if not outer[:start].rpartition('\n')[2].strip() and (not outer[end:].partition('\n')[0].strip()):
            return True
        start = outer.find(inner, start + 1)
    return False

def _images_replaced(stored: Any, held: Any) -> bool:
    """True when *held* is *stored* with at least one image part swapped for a text part, all else equal."""
    from agent.context_compressor import _is_image_part
    if not (isinstance(stored, list) and isinstance(held, list)) or len(stored) != len(held):
        return False
    swapped = False
    for was, now in zip(stored, held):
        if was == now:
            continue
        if not (_is_image_part(was) and isinstance(now, dict) and (now.get('type') == 'text')):
            return False
        swapped = True
    return swapped

class CoverageRules:

    def _index_held_dicts(self, compacted_messages: list[dict[str, Any]]) -> tuple[dict, dict]:
        """Held dicts by the name they carry: ``_row_id`` -> (index, identity, uid); uid -> [(index, identity)].
        A dict naming neither is never a claim: equal text is not the same occurrence."""
        by_row: dict[int, tuple[int, tuple[Any, ...], Optional[str]]] = {}
        by_uid: dict[str, list[tuple[int, tuple[Any, ...]]]] = {}
        for index, message in enumerate(compacted_messages):
            if not isinstance(message, dict):
                continue
            identity = self._row_identity(message.get('role', 'unknown'), message.get('content'), message.get('tool_call_id'), _parse_tool_calls(message.get('tool_calls')))
            row_id = message.get('_row_id')
            uid = message_uid_or_none(message)
            if isinstance(row_id, int) and (not isinstance(row_id, bool)) and (row_id > 0):
                by_row.setdefault(row_id, (index, identity, uid))
            elif uid is not None:
                by_uid.setdefault(uid, []).append((index, identity))
        return (by_row, by_uid)

    def _claim_stored_copy(self, row, compacted_messages, by_row, by_uid, claimed) -> Optional[int]:
        """First pass: the unclaimed dict naming *row* (``_row_id``, else uid) that replays exactly as it does."""
        identity = self._row_identity(row['role'], self._decode_content(row['content']), row['tool_call_id'], _parse_tool_calls(row['tool_calls']))
        named = by_row.get(int(row['id']))
        candidates = [named[0]] if named is not None and named[1] == identity else []
        row_uid = row[MESSAGE_UID] or None
        candidates += [index for index, held in by_uid.get(row_uid, ()) if held == identity] if row_uid else []
        return next((index for index in candidates if index not in claimed and self._replays_as(row, compacted_messages[index], True)), None)

    def _rewritten_carry(self, row, row_uid, compacted_messages, by_row, by_uid, claimed) -> Optional[int]:
        """Second pass: the one unclaimed dict naming *row* (``_row_id`` with the row's uid, else its uid alone)
        whose different content the compressor's rewrite of that row explains; None means clone."""
        named = by_row.get(int(row['id']))
        if named is not None and named[2] == row_uid:
            candidates = [named[0]]
        else:
            candidates = [index for index, _identity in by_uid.get(row_uid, ())]
        candidates = [index for index in candidates if index not in claimed]
        if len(candidates) != 1:
            return None
        if self._rewrite_explains(row, compacted_messages[candidates[0]]):
            return candidates[0]
        return None

    def _replays_as(self, row, held: dict[str, Any], same_content: bool) -> bool:
        """Whether *held* replays the sidecars the next request would read from *row* (``api_content`` and the
        reasoning carriers in ``REPLAY_SIDECARS``), compared through the writer's own serializer.

        A sidecar the copy carries must equal the row's: a different one is an older version (a later
        ``set_message_api_content``, a re-stamped reasoning item). A copy WITHOUT the row's ``api_content``
        stands for it only when its own content is those bytes (the flush stores sanitize-changed text as the
        sidecar), or when the compressor rewrote the content, which drops the stale sidecar by design."""
        from agent.transcript_repair import REPLAY_SIDECARS
        serialized = self._serialized_message_row(row['session_id'], held, float(row['timestamp'] or 0))
        content = self._decode_content(row['content'])
        row_api, held_api = (None if api == text else api for api, text in ((row['api_content'], content), (serialized['api_content'], held.get('content'))))
        if any(serialized[column] is not None and serialized[column] != row[column] for column in REPLAY_SIDECARS):
            return False
        if held_api is not None or row_api is None:
            return held_api == row_api
        return not same_content or held.get('content') == row_api

    @staticmethod
    def _copy_of_current_row(row, held: dict[str, Any]) -> bool:
        """Whether *held* was copied from *row*'s current version, so extra text in it is the compressor's.

        Containment alone cannot tell "the compressor added text" from "the row lost text after the copy"
        (an in-place edit that shortens it). Only the stored-row digest a flushed dict carries settles it: a
        mismatch means the row was rewritten after the copy. A copy without one (a bare uid copy, or a
        row-addressed load, which omits the digest by design) may predate any number of rewrites, so the row
        is cloned: a duplicate, never an older instruction in place of the current one."""
        from agent.transcript_repair import transcript_row_snapshot
        snapshot = held.get(DB_ROW_SNAPSHOT)
        return isinstance(snapshot, str) and snapshot == transcript_row_snapshot(row)

    def _rewrite_explains(self, row, held: dict[str, Any]) -> bool:
        """True when *held* differs from stored *row* only the way the compressor rewrites a carry it keeps:
        image parts replaced by text placeholders, or, for a copy of the row's current version, the row's
        text kept verbatim as whole lines inside a longer text (a summary merged in, prior-context header and
        markers around it); and its sidecars still replay the row's. The summary flag alone is not enough: a
        flagged copy taken before an in-place rewrite of the row would put the older text back."""
        role = row['role']
        if (held.get('role'), held.get('tool_call_id') or None) != (role, row['tool_call_id'] or None):
            return False
        if (_parse_tool_calls(held.get('tool_calls')) or None) != (_parse_tool_calls(row['tool_calls']) or None):
            return False
        stored = self._loaded_view_content(role, self._decode_content(row['content']))
        content = self._loaded_view_content(role, held.get('content'))
        if not self._replays_as(row, held, stored == content):
            return False
        if _images_replaced(stored, content):
            return True
        if not self._copy_of_current_row(row, held):
            return False
        stored_text = _text_of(stored)
        return bool(stored_text.strip()) and _holds_as_block(stored_text, _text_of(content))

    @staticmethod
    def _carried_tail_slots(carried: dict[int, int], compacted_count: int, tail_count: int) -> int:
        """How many of the carried tail's *tail_count* dicts name a row in *carried*: those originals sit
        above the watermark, so the positional rewind below it must take that many fewer rows."""
        if tail_count <= 0:
            return 0
        return sum(1 for index in carried.values() if index >= compacted_count - int(tail_count))

    def _proved_coverage(self, conn, session_id: str, covered_ids: Optional[list[int]], unresolved_held: Optional[list[dict[str, Any]]], watermark: Optional[int]=None) -> Optional[tuple[list[int], set[int]]]:
        """``(ids safe to archive as summarized, ids merged into another held dict)``, or None when
        a durable held row cannot be named.

        An unresolved dict that still carries the persist marker was loaded from the DB.
        Failing to name it means the watermark path, which archives the rows the compressor
        saw, including ones whose ids were stripped. A marker-less miss is an unpersisted
        turn: it names nothing, and it is not a reason to abandon the ids we do have.
        Several active rows with the same content are ambiguous, so that also abandons,
        and so does a merged dict whose run cannot be named.
        The second set holds only merges the caller could not count: a dict that lists its
        own ``_absorbed_row_ids`` is already counted in ``tail_count``.
        """
        if covered_ids is None:
            return None
        from agent.context_compressor import _DB_PERSISTED_MARKER
        from agent.conversation_compression_archive import ABSORBED_ROW_IDS, MERGED_DURABLE_ROWS, OWN_ROW, RETIRED_DURABLE_ROWS, RETIRED_ROW
        proved = [int(row_id) for row_id in covered_ids if isinstance(row_id, int) and row_id > 0]
        merged_away: set[int] = set()
        for message in unresolved_held or ():
            if not isinstance(message, dict):
                continue
            if message.get(RETIRED_ROW):
                matches = self._matching_retired_ids(conn, session_id, message, watermark)
                if len(matches) != 1:
                    return None
                proved.extend(matches)
                if not message.get(OWN_ROW):
                    merged_away.update(matches)
                continue
            if any(isinstance(row, dict) and row.get(OWN_ROW) for row in message.get(RETIRED_DURABLE_ROWS) or ()):
                continue
            run = self._merged_user_run(conn, session_id, message, watermark)
            if message.get(MERGED_DURABLE_ROWS) and (not run):
                return None
            matches = [] if run else self._matching_active_ids(conn, session_id, message)
            if len(matches) > 1 or (message.get(_DB_PERSISTED_MARKER) and len(matches) != 1 and (not run)):
                return None
            proved.extend(matches or run)
            merged_away.update(set(run[1:]) - set(message.get(ABSORBED_ROW_IDS) or ()))
        return (list(dict.fromkeys(proved)), merged_away)

    @staticmethod
    def _uncounted_merged_rows(tail: list[dict[str, Any]]) -> int:
        """Durable rows behind the carried *tail* beyond one per dict, for the positional rewind.

        The watermark path cannot name a merged dict's run, so it widens by the stamp, less the
        rows the dict lists in ``_absorbed_row_ids``: those are already counted in ``tail_count``.
        Rows the repair dropped behind a dict, or folded into an assistant turn, on a reload
        without ids are in neither, so their count is added. A dict that holds a ``_row_id`` was
        written back as a single row by an earlier compaction.
        """
        from agent.conversation_compression_archive import ABSORBED_ROW_IDS, MERGED_DURABLE_ROWS, UNNAMED_DURABLE_ROWS

        def behind(message: dict[str, Any]) -> int:
            merged, unnamed = (message.get(MERGED_DURABLE_ROWS), message.get(UNNAMED_DURABLE_ROWS))
            unlisted = merged - 1 - len(message.get(ABSORBED_ROW_IDS) or ()) if type(merged) is int else 0
            return max(0, unlisted) + (unnamed if type(unnamed) is int else 0)
        return sum(behind(message) for message in tail if isinstance(message, dict) and (not isinstance(message.get('_row_id'), int)))

    @staticmethod
    def _tail_originals(covered_active: list[int], tail_count: int, merged_away: set[int]) -> list[int]:
        """Newest rows behind *tail_count* carried dicts; a dict that merged rows stands for each of them."""
        width = int(tail_count)
        while True:
            window = covered_active[-width:]
            need = int(tail_count) + sum(1 for row_id in window if row_id in merged_away)
            if need <= width or width >= len(covered_active):
                return window
            width = need
