"""Coverage proofs over a detached active transcript, without database I/O.

Reuse the existing pure identity/version rules. SQL repositories supply only
the owning store's rows; no SQLite connection or SQL adapter is inherited.
"""
from hermes_db.domains.sessions.codec import TranscriptCodec
from hermes_db.domains.sessions.coverage import CoverageRules
from collections import Counter
from agent.message_metadata import DB_ROW_SNAPSHOT, message_uid_or_none
from agent.transcript_repair import transcript_row_snapshot
from hermes_cli.timefmt import coerce_epoch
from hermes_db.domains.sessions.codec import _parse_tool_calls

class Coverage(TranscriptCodec, CoverageRules):

    def __init__(self, rows):
        self.rows = rows
        self.by_id = {row['id']: row for row in rows}

    def identity(self, message, *, stored=False):
        content = self._decode_content(message['content']) if stored else message.get('content')
        return self._row_identity(message.get('role', 'unknown'), content, message.get('tool_call_id'), _parse_tool_calls(message.get('tool_calls')))

    def carried_tail(self, tail_ids, batch):
        by_row, by_uid = self._index_held_dicts(batch)
        rows = [self.by_id[rid] for rid in tail_ids]
        carried, weak = ({}, set())
        for row in rows:
            index = self._claim_stored_copy(row, batch, by_row, by_uid, set(carried.values()))
            if index is not None:
                carried[row['id']] = index
        tail = set(tail_ids)
        elsewhere = {row['message_uid'] for row in self.rows if row['id'] not in tail}
        counts = Counter(row['message_uid'] for row in rows if row['message_uid'])
        for row in rows:
            uid = row['message_uid']
            if row['id'] in carried or not uid or counts[uid] != 1 or (uid in elsewhere):
                continue
            index = self._rewritten_carry(row, uid, batch, by_row, by_uid, set(carried.values()))
            if index is not None:
                carried[row['id']] = index
                weak.add(row['id'])
        return (carried, weak)

    def carried_originals(self, batch):
        by_key = {}
        for row in self.rows:
            timestamp = coerce_epoch(row['timestamp'], field='message timestamp')
            if timestamp is not None:
                by_key.setdefault((*self.identity(row, stored=True), timestamp), []).append(row['id'])
        found = []
        for message in batch:
            if not isinstance(message, dict):
                continue
            rid = exact_id(message)
            identity = self.identity(message)
            if rid in self.by_id and self.identity(self.by_id[rid], stored=True) == identity:
                found.append(rid)
                continue
            timestamp = coerce_epoch(message.get('timestamp'), field='message timestamp')
            matches = by_key.get((*identity, timestamp), []) if timestamp is not None else []
            if len(matches) == 1:
                found.append(matches[0])
        return list(dict.fromkeys(found))

    def _matching_active_ids(self, conn, session_id, message):
        content = message.get('content')
        if not isinstance(content, str):
            return []
        stored = self._encode_content(self._loaded_view_content(message.get('role', 'unknown'), content))
        return [row['id'] for row in self.rows if row['role'] == message.get('role') and row['content'] == stored]

    def _matching_retired_ids(self, conn, session_id, retired, watermark=None):
        result = []
        for row in self.rows:
            if row['role'] != str(retired.get('role') or '') or (watermark is not None and row['id'] > int(watermark)):
                continue
            content = self._loaded_view_content(row['role'], self._decode_content(row['content']))
            if (content or None) != (retired.get('content') or None):
                continue
            if (row['tool_call_id'] or None) != (retired.get('tool_call_id') or None):
                continue
            calls = _parse_tool_calls(row['tool_calls']) or []
            ids = [call.get('id') for call in calls if isinstance(call, dict)] if isinstance(calls, list) else []
            if ids == list(retired.get('tool_call_ids') or ()):
                result.append(row['id'])
        return result

    def _merged_user_run(self, conn, session_id, message, watermark=None):
        from agent.conversation_compression_archive import MERGED_DURABLE_ROWS, OWN_ROW, RETIRED_DURABLE_ROWS
        from gateway.message_timestamps import strip_leading_message_timestamps
        content, width = (message.get('content'), message.get(MERGED_DURABLE_ROWS))
        if message.get('role') != 'user' or not isinstance(content, str) or type(width) is not int or (width < 2):
            return []
        content, _ = strip_leading_message_timestamps(content)
        retired_ids = set()
        for retired in message.get(RETIRED_DURABLE_ROWS) or ():
            if retired.get(OWN_ROW):
                continue
            matches = self._matching_retired_ids(conn, session_id, retired, watermark)
            if len(matches) != 1:
                return None
            retired_ids.update(matches)
        rows = [row for row in self.rows if row['id'] not in retired_ids and (watermark is None or row['id'] <= int(watermark))]
        runs = self._matching_runs(rows, content, width)
        return None if len(runs) > 1 else runs[0] if runs else []

    def _matching_runs(self, rows, content, width):
        runs = []
        for start in range(len(rows)):
            merged = ''
            for end in range(start, min(len(rows), start + width)):
                row = rows[end]
                part = self._loaded_view_content(row['role'], self._decode_content(row['content']))
                if row['role'] != 'user' or not isinstance(part, str):
                    break
                merged = f'{merged}\n\n{part}' if merged and part else merged or part
                if not content.startswith(merged):
                    break
                if end - start + 1 == width and merged == content:
                    runs.append([row['id'] for row in rows[start:end + 1]])
        return runs

    def mismatches(self, held):
        from agent.context_compressor import _DB_PERSISTED_MARKER
        latest = {(row['message_uid'], row['role']): row for row in self.rows if row['message_uid']}
        result = []
        for message in held:
            if not isinstance(message, dict) or not message.get(_DB_PERSISTED_MARKER):
                continue
            if message.get('role') not in ('user', 'assistant', 'tool'):
                continue
            rid = exact_id(message)
            snapshot = message.get(DB_ROW_SNAPSHOT)
            row = self.by_id.get(rid) if rid is not None else latest.get((message_uid_or_none(message), message.get('role'))) if isinstance(snapshot, str) else None
            if row is None:
                continue
            differs = transcript_row_snapshot(row) != snapshot if isinstance(snapshot, str) else self.identity(message) != self.identity(row, stored=True)
            if differs:
                result.append(row['id'])
        return result

def exact_id(message):
    rid = message.get('_row_id')
    return rid if type(rid) is int and rid > 0 else None
