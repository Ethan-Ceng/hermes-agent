"""Pure TranscriptCodec shared by native and PostgreSQL session persistence; no connections or storage lifecycle."""
from __future__ import annotations
from agent.message_sanitization import _sanitize_surrogates
from agent.message_metadata import DATA_USE
from agent.context_compressor import MODEL_ONLY_DISPLAY_METADATA_KEY
from agent.context_compressor import _DB_PERSISTED_MARKER as _DB_PERSISTED_MARKER_KEY
from hermes_state_identity import _tool_call_uid_map
from typing import Optional
from agent.message_metadata import message_uid_or_none
from hermes_state_identity import _stable_tool_key
from hermes_state_identity import _tool_call_uid_or_none
from agent.memory_context import sanitize_context
from hermes_state_identity import _tool_call_uids_json
from hermes_state_identity import _restore_identity_columns
from agent.message_metadata import TOOL_CALL_UIDS
from agent.message_metadata import index_tool_call_uids
from hermes_state_compaction_display import later_tool_copy_ids
from agent.message_metadata import resolve_tool_call_uid
import json
from agent.message_metadata import DB_ROW_SNAPSHOT
from hermes_state_identity import _absorbed_uids_json
from agent.message_metadata import mint_uid
from agent.message_sanitization import coalesce_tool_call_id
import hashlib
from agent.message_metadata import lift_data_use
from hermes_db.domains.sessions.rules import _json_or
from hermes_state_identity import _uid_list
from agent.message_metadata import TOOL_CALL_UID
from agent.context_compressor import split_user_originated_turn
from typing import Any
import logging
logger = logging.getLogger('hermes_state')
_MESSAGE_WRITE_COLUMNS = ('session_id', 'role', 'content', 'tool_call_id', 'tool_calls', 'tool_name', 'effect_disposition', 'timestamp', 'token_count', 'finish_reason', 'reasoning', 'reasoning_content', 'reasoning_details', 'codex_reasoning_items', 'codex_message_items', 'platform_message_id', 'observed', '_compressed_summary', 'active', 'api_content', 'display_kind', 'display_metadata', 'display_identity', 'message_uid', 'absorbed_message_uids', 'tool_call_uids', 'tool_call_uid')
_MESSAGE_SCHEMA_KEYS = frozenset(_MESSAGE_WRITE_COLUMNS) | {'id', 'compacted', 'display_order'}
_INVALID = object()

def _parse_tool_calls(tool_calls: Any) -> Any:
    """tool_calls is a list (live agent) or JSON string (import/export); parse so json.dumps never double-encodes."""
    if not isinstance(tool_calls, str):
        return tool_calls
    try:
        return json.loads(tool_calls)
    except (json.JSONDecodeError, TypeError):
        return []

def _scrub_surrogates(value: Any) -> Any:
    """Lone surrogates make sqlite3 raise UnicodeEncodeError and abort the whole write."""
    return _sanitize_surrogates(value) if isinstance(value, str) else value

class TranscriptCodec:
    _CONTENT_JSON_PREFIX = '\x00json:'
    REACTIONS_METADATA_KEY = 'reactions'

    @classmethod
    def _encode_content(cls, content: Any) -> Any:
        """Serialize list/dict content (multimodal parts) as a sentinel-prefixed JSON string (sqlite3 binds
        only scalars). Lone UTF-16 surrogates (unsanitized web-scraped tool results) are scrubbed here: left
        raw, sqlite3 raises UnicodeEncodeError and the session silently stops persisting. Pairs with
        :meth:`_decode_content`.

        A literal string carrying the reserved ``\\x00json:`` prefix is indistinguishable from
        stored structured content, so it is JSON-string-wrapped (decoded back verbatim on read)
        instead of written raw — a crafted import can't smuggle the marker in and have the read
        path decode attacker-chosen structure."""
        if isinstance(content, str):
            content = _sanitize_surrogates(content)
            if not content.startswith(cls._CONTENT_JSON_PREFIX):
                return content
        elif content is None or isinstance(content, (bytes, int, float)):
            return content
        try:
            return cls._CONTENT_JSON_PREFIX + json.dumps(content)
        except (TypeError, ValueError):
            return _sanitize_surrogates(str(content))

    @classmethod
    def _decode_content(cls, content: Any) -> Any:
        """Reverse :meth:`_encode_content`; returns scalars unchanged. Fail closed: a reserved-prefix
        string that isn't valid JSON (a legacy/malformed marker row) returns the raw string."""
        if isinstance(content, str) and content.startswith(cls._CONTENT_JSON_PREFIX):
            return _json_or(content[len(cls._CONTENT_JSON_PREFIX):], content, 'Failed to decode JSON-encoded message content; returning raw string')
        return content

    @staticmethod
    def _encode_display_metadata(display_metadata: Any) -> Optional[str]:
        """Serialize ``display_metadata`` for its TEXT column; an already-serialized JSON string
        (import/replace paths) is not double-encoded."""
        if not display_metadata:
            return None
        if isinstance(display_metadata, str):
            display_metadata = _json_or(display_metadata, _INVALID, 'Ignoring non-JSON display metadata on write')
            if display_metadata is _INVALID:
                return None
            if not isinstance(display_metadata, dict):
                logger.warning('Ignoring non-object display metadata on write')
                return None
        elif not isinstance(display_metadata, dict):
            logger.warning('Ignoring unexpected display metadata type on write: %s', type(display_metadata).__name__)
            return None
        return json.dumps(display_metadata)

    @staticmethod
    def _decode_display_metadata(raw: Any) -> Optional[dict[str, Any]]:
        """Decode a ``display_metadata`` column to a dict (never raw TEXT: the desktop does ``'task_count'
        in meta``). Pre-guard rows are double-encoded, so a second string layer is unwrapped."""
        if raw is None:
            return None
        meta = raw
        for _ in range(2):
            if isinstance(meta, str):
                meta = _json_or(meta, _INVALID, 'Ignoring invalid display metadata on message row')
        if meta is _INVALID:
            return None
        if not isinstance(meta, dict):
            logger.warning('Ignoring non-object display metadata on message row')
            return None
        return meta

    @staticmethod
    def _reasoning_json_text(value: Any) -> Optional[str]:
        """Serialize a structured reasoning field for its TEXT column. Strings are stored as-is: round-trips
        (get_messages -> replace_messages) hand back raw TEXT; re-dumping would double-encode it and
        reasoning-replay consumers (``isinstance(..., list)``) would drop it."""
        return None if not value else value if isinstance(value, str) else json.dumps(value)

    def _message_row_params(self, session_id: str, role: str, msg: dict[str, Any], tool_calls: Any, message_timestamp: float, *, keep_reasoning: bool) -> tuple:
        """Bind values for ``_INSERT_MESSAGE_SQL`` from one message dict (*tool_calls* already parsed;
        *keep_reasoning* False NULLs every reasoning column). ``platform_message_id`` falls back to
        ``message_id`` (yuanbao's message-dict convention)."""
        _str_or_none = lambda v: _scrub_surrogates(v) if isinstance(v, str) else None
        _reasoning = lambda key: msg.get(key) if keep_reasoning else None
        encoded_content = self._encode_content(msg.get('content'))
        encoded_tool_calls = json.dumps(tool_calls) if tool_calls else None
        encoded_tool_name = _scrub_surrogates(msg.get('tool_name'))
        display_metadata = msg.get('display_metadata')
        if msg.get(DATA_USE) and isinstance(display_metadata, (dict, type(None))):
            display_metadata = {**(display_metadata or {}), DATA_USE: list(msg[DATA_USE])}
        display_metadata = self._encode_display_metadata(display_metadata)
        identity_row = {'role': role, 'content': encoded_content, 'timestamp': message_timestamp, 'tool_call_id': msg.get('tool_call_id'), 'tool_calls': encoded_tool_calls, 'tool_name': encoded_tool_name, 'display_kind': msg.get('display_kind'), 'display_metadata': display_metadata}
        return (session_id, role, encoded_content, msg.get('tool_call_id'), encoded_tool_calls, encoded_tool_name, msg.get('effect_disposition'), message_timestamp, msg.get('token_count'), msg.get('finish_reason'), _scrub_surrogates(_reasoning('reasoning')), _scrub_surrogates(_reasoning('reasoning_content')), *(self._reasoning_json_text(_reasoning(k)) for k in ('reasoning_details', 'codex_reasoning_items', 'codex_message_items')), msg.get('platform_message_id') or msg.get('message_id'), 1 if msg.get('observed') else 0, 1 if msg.get('_compressed_summary') else 0, 1, _str_or_none(msg.get('api_content')), _str_or_none(msg.get('display_kind')), display_metadata, self._display_identity(self._display_dedupe_key(identity_row)), message_uid_or_none(msg), _absorbed_uids_json(msg), _tool_call_uids_json(msg), _tool_call_uid_or_none(msg))

    @staticmethod
    def _stamp_tool_call_uids(msg: dict[str, Any], tool_calls: Any, batch_index: dict[str, str]) -> None:
        """Per-occurrence tool-call identity at insert: an assistant row gets a uid for every tool call that
        has none yet (``_tool_call_uids``, keyed by the effective provider id, which stays untouched); a
        tool-result row that has none is resolved through *batch_index*, the calls the same batch's
        assistant rows named. A result flushed in a later batch is resolved from the live list by the flush
        (``tool_call_uid_from_history``) or, on restore, from the preceding assistant row."""
        role = msg.get('role')
        if role == 'assistant' and tool_calls:
            uids = _tool_call_uid_map(msg)
            for tc in tool_calls:
                call_id = coalesce_tool_call_id(tc)
                if call_id and call_id not in uids:
                    uids[call_id] = mint_uid()
            if uids:
                msg[TOOL_CALL_UIDS] = uids
            index_tool_call_uids(batch_index, msg)
        elif role == 'user':
            batch_index.clear()
        elif role == 'tool' and _tool_call_uid_or_none(msg) is None:
            uid = resolve_tool_call_uid(batch_index, msg.get('tool_call_id'))
            if uid:
                msg[TOOL_CALL_UID] = uid

    def _serialized_message_row(self, session_id: str, msg: dict[str, Any], message_timestamp: float) -> dict[str, Any]:
        """Serialize one live message with the exact durable shape used by INSERT."""
        role = msg.get('role', 'unknown')
        params = self._message_row_params(session_id, role, msg, _parse_tool_calls(msg.get('tool_calls')), message_timestamp, keep_reasoning=role == 'assistant')
        return dict(zip(_MESSAGE_WRITE_COLUMNS, params))

    def _decoded_repair_row(self, row) -> dict[str, Any]:
        """Decode one durable row without replay dedupe, alternation repair, or content stripping."""
        msg: dict[str, Any] = {'role': row['role'], 'content': self._decode_content(row['content'])}
        for column in ('tool_call_id', 'tool_name', 'effect_disposition', 'token_count', 'finish_reason'):
            if row[column] is not None:
                msg[column] = row[column]
        if row['tool_calls']:
            msg['tool_calls'] = _json_or(row['tool_calls'], [], 'Failed to deserialize repaired tool_calls, falling back to []')
        if row['platform_message_id'] is not None:
            msg['message_id'] = row['platform_message_id']
            msg['platform_message_id'] = row['platform_message_id']
        if row['observed']:
            msg['observed'] = True
        if row['_compressed_summary']:
            msg['_compressed_summary'] = True
        _restore_identity_columns(row, msg)
        if row['api_content'] is not None:
            msg['api_content'] = row['api_content']
        if row['display_kind'] is not None:
            msg['display_kind'] = row['display_kind']
        if row['display_metadata'] is not None:
            metadata = self._decode_display_metadata(row['display_metadata'])
            if metadata is not None:
                msg['display_metadata'] = metadata
        if row['role'] == 'assistant':
            for column in ('reasoning', 'reasoning_content'):
                if row[column] is not None:
                    msg[column] = row[column]
            for column in ('reasoning_details', 'codex_reasoning_items', 'codex_message_items'):
                if row[column]:
                    msg[column] = _json_or(row[column], None, f'Failed to deserialize repaired {column}, falling back to None')
        return msg

    @classmethod
    def _row_identity(cls, role: str, content: Any, tool_call_id: Any, tool_calls: Any) -> tuple:
        """The (role, content, tool_call_id, tool_calls) columns a message writes — the identity the
        kept-prefix match compares. *content* is passed through the loader's lens first so a message
        read back from the DB matches the row it came from."""
        return (role, cls._encode_content(cls._loaded_view_content(role, content)), tool_call_id, json.dumps(tool_calls) if tool_calls else None)

    @staticmethod
    def _loaded_view_content(role: str, content: Any) -> Any:
        """Content as ``_rows_to_messages`` hands it to callers: user/assistant strings are sanitized and
        stripped on load, so a reloaded session's messages must be compared to rows through the same lens."""
        if role in {'user', 'assistant'} and isinstance(content, str):
            return sanitize_context(content).strip()
        return content

    def _display_dedupe_key(self, row) -> tuple[Any, ...]:
        """Historical display identity, including normalized live content from user handoff carriers."""
        dedupe_content = row['content']
        if row['role'] == 'user':
            handoff, live_view = split_user_originated_turn({'role': 'user', 'content': self._decode_content(row['content']), 'display_kind': row['display_kind'], 'display_metadata': self._decode_display_metadata(row['display_metadata'])})
            if handoff is not None and live_view is not None:
                dedupe_content = self._encode_content(live_view.get('content'))
        return _stable_tool_key(row) or (row['role'], dedupe_content, row['timestamp'], row['tool_call_id'], row['tool_calls'], row['tool_name'])

    def _is_model_only_row(self, row) -> bool:
        """Python twin of :data:`DISPLAY_VISIBLE_SQL`."""
        return bool((self._decode_display_metadata(row['display_metadata']) or {}).get(MODEL_ONLY_DISPLAY_METADATA_KEY))

    @staticmethod
    def _display_identity(key: tuple[Any, ...]) -> bytes:
        """Fixed-width durable identity for indexed display-generation lookup."""
        return hashlib.sha256(repr(key).encode('utf-8', 'surrogatepass')).digest()

    @staticmethod
    def _fold_summary_carrier(row, key: Any, first_by_uid: dict) -> Any:
        """The display identity both display reads give *row*, scanning rows in ``id`` order.

        A compaction carrier keeps its message's ``message_uid`` but not its content (the prior tail
        wrapped around the summary), so it is a copy of the first row with that uid: shown once."""
        uid = row['message_uid']
        if not uid:
            return key
        if row['_compressed_summary']:
            return first_by_uid.get(uid, key)
        first_by_uid.setdefault(uid, key)
        return key

    def _dedupe_display_generations(self, rows, *, drop_removed: bool=False, first_ids: Optional[dict]=None):
        """Collapse compaction generations so each logical message appears once (the protected tail is copied
        into each generation: same role/content/timestamp, different ``active``/id); prefer the live row, then
        the newest. The ONE definition every display projection shares. *rows* must be ordered by ``id``.

        *drop_removed*: *rows* also hold the removed rows (``active=0, compacted=0``: rewound, or replaced by a
        newer copy) and ``compacted``. A message whose newest copy is removed is not shown, so a rewind in a
        compression child never brings back the parent's copy. Copies share the display key or ``message_uid``
        (a micro-compaction merge also stands for the rows it absorbed). *first_ids* gets each kept row's id ->
        its message's first durable row id, a removed copy's included (a carried tail's superseded original):
        the key no compaction or rotation moves.

        Storage interface: port as ``display_generations`` (``first_ids`` is ``session.transcript``'s)."""
        seen: dict[tuple[Any, ...], Any] = {}
        first_id: dict[tuple[Any, ...], int] = {}
        uid_key: dict[Any, tuple[Any, ...]] = {}
        removed: dict[Any, bool] = {}
        identities: dict[tuple[Any, ...], list[Any]] = {}
        removed_ts: set[Any] = set()
        removed_first: dict[Any, int] = {}
        rows = rows if isinstance(rows, list) else list(rows)
        later_copies = later_tool_copy_ids(self, rows)
        if drop_removed:
            removed_ts = {row['timestamp'] for row in rows if not row['active'] and (not row['compacted'])}
            drop_removed = bool(removed_ts)
        for row in rows:
            copies, key = (None, None)
            if drop_removed:
                gone = not row['active'] and (not row['compacted'])
                stored = row['display_identity'] if gone else None
                key = None if stored else self._display_dedupe_key(row)
                hashed = stored or (self._display_identity(key) if key is not None and (gone or row['timestamp'] in removed_ts) else None)
                copies = [*((hashed,) if hashed else ()), *(('uid', uid) for uid in (row['message_uid'], *_uid_list(row['absorbed_message_uids'])) if uid)]
                removed.update(dict.fromkeys(copies, gone))
                if gone:
                    for copy in copies:
                        removed_first.setdefault(copy, row['id'])
                    continue
            if self._is_model_only_row(row) or row['id'] in later_copies:
                continue
            key = key or self._display_dedupe_key(row)
            key = self._fold_summary_carrier(row, key, uid_key)
            cur = seen.get(key)
            if cur is None or (row['active'], row['id']) > (cur['active'], cur['id']):
                seen[key] = row
                identities[key] = copies
            first_id[key] = min(first_id.get(key, row['id']), row['id'])
        keys = sorted(seen, key=first_id.__getitem__)
        if drop_removed:
            keys = [key for key in keys if not any(removed[copy] for copy in identities[key])]
        if first_ids is not None:
            first_ids.update((seen[key]['id'], min([first_id[key], *(removed_first[copy] for copy in identities[key] or () if copy in removed_first)])) for key in keys)
        return [seen[key] for key in keys]

    def _row_to_message_dict(self, row, *, warn_context: str, summary_flag: bool) -> dict[str, Any]:
        """``dict(row)`` with content/tool_calls/display_metadata decoded; *summary_flag* keeps
        ``_compressed_summary`` only as ``True``."""
        msg = dict(row)
        msg.pop('display_identity', None)
        msg.pop('display_order', None)
        if summary_flag and msg.pop('_compressed_summary', 0):
            msg['_compressed_summary'] = True
        msg['content'] = self._decode_content(msg['content'])
        if msg.get('tool_calls'):
            msg['tool_calls'] = _json_or(msg['tool_calls'], [], f'Failed to deserialize tool_calls in {warn_context}, falling back to []')
        if msg.get('display_metadata') is not None:
            msg['display_metadata'] = self._decode_display_metadata(msg['display_metadata'])
        for key, value in list(msg.items()):
            if key not in _MESSAGE_SCHEMA_KEYS and isinstance(value, (bytes, bytearray)):
                msg.pop(key)
        return msg

    def _dedupe_replayed_user(self, messages, msg, exact_user_clones) -> tuple[bool, Any]:
        """Ancestor-lineage dedupe of one decoded user *msg* -> ``(skip, exact_clone_key)``. Rotation
        column-clones the concurrent tail into the child, so copies need not be adjacent: the exact
        ``(timestamp, canonical content)`` clone index is checked first, then the adjacent heuristic. A
        rotated child carrier wins over the ancestor copy."""
        canonical_content = self._canonical_replayed_user_content(msg)[0]
        exact_clone_key = self._exact_replayed_user_clone_key(msg.get('timestamp'), canonical_content)
        previous_exact = exact_user_clones.get(exact_clone_key) if exact_clone_key is not None else None
        duplicate = None
        if previous_exact is not None:
            previous_index = next((i for i, candidate in enumerate(messages) if candidate is previous_exact), None)
            if previous_index is not None:
                duplicate = (previous_index, True)
        if duplicate is None:
            duplicate = self._find_duplicate_replayed_user_message(messages, msg)
        if duplicate is None:
            return (False, exact_clone_key)
        duplicate_index, prefer_current = duplicate
        if prefer_current:
            messages.pop(duplicate_index)
        return (not prefer_current, exact_clone_key)

    def _rows_to_conversation(self, rows, *, session_id: str, include_ancestors: bool, repair_alternation: bool, include_row_ids: bool=False, include_summary_markers: bool=False) -> list[dict[str, Any]]:
        """Decode fetched rows (ordered by id, pre-filtered) into OpenAI format, stable key order. Every dict is
        stamped ``_DB_PERSISTED_MARKER_KEY`` (born durable) so an identity-losing handoff never re-appends the
        transcript on flush. Unaddressed live-replay projections also carry the stored-row CAS digest: if a later rewrite
        loses its physical ``_row_id``, logical ``message_uid`` can recover the row without guessing by
        mutable payload while the digest still fences a concurrent winner. ``_row_id`` is opt-in (gateway
        reactions); reasoning restored on assistant rows only; ``api_content`` VERBATIM (no sanitize/strip)
        so replay keeps the provider prompt cache byte-stable."""
        from agent.message_sanitization import _strip_background_review_harness, _strip_stale_tool_call_markers
        from agent.transcript_repair import transcript_row_snapshot
        stamp_snapshot = repair_alternation and (not include_row_ids)
        messages = []
        exact_user_clones: dict[tuple[Any, str], dict[str, Any]] = {}
        tool_uid_index: dict[str, str] = {}
        unindexed_tool_owners: list[dict[str, Any]] = []
        for row in rows:
            content = self._loaded_view_content(row['role'], self._decode_content(row['content']))
            msg = {'role': row['role'], 'content': content, _DB_PERSISTED_MARKER_KEY: True}
            if stamp_snapshot:
                msg[DB_ROW_SNAPSHOT] = transcript_row_snapshot(row)
            if include_row_ids and row['id'] is not None:
                msg['_row_id'] = row['id']
            _restore_identity_columns(row, msg)
            msg.update((col, row[col]) for col in ('api_content', 'display_kind') if row[col])
            if row['display_metadata'] and (decoded := self._decode_display_metadata(row['display_metadata'])) is not None:
                msg['display_metadata'] = decoded
                lift_data_use(msg)
            if include_summary_markers and row['_compressed_summary']:
                msg['_compressed_summary'] = True
            msg.update((col, row[col]) for col in ('timestamp', 'tool_call_id', 'tool_name', 'effect_disposition') if row[col])
            if row['tool_calls']:
                msg['tool_calls'] = _json_or(row['tool_calls'], [], 'Failed to deserialize tool_calls in conversation replay, falling back to []')
            if row['platform_message_id']:
                msg['message_id'] = row['platform_message_id']
            if row['observed']:
                msg['observed'] = True
            if row['role'] == 'assistant':
                msg.update((col, row[col]) for col in ('finish_reason', 'reasoning') if row[col])
                if row['reasoning_content'] is not None:
                    msg['reasoning_content'] = row['reasoning_content']
                msg.update((col, _json_or(row[col], None, f'Failed to deserialize {col}, falling back to None')) for col in ('reasoning_details', 'codex_reasoning_items', 'codex_message_items') if row[col])
                if msg.get('tool_calls'):
                    unindexed_tool_owners.append(msg)
            elif row['role'] == 'user':
                tool_uid_index.clear()
                unindexed_tool_owners.clear()
            elif row['role'] == 'tool' and (not row['tool_call_uid']) and row['tool_call_id']:
                for owner in unindexed_tool_owners:
                    index_tool_call_uids(tool_uid_index, owner)
                unindexed_tool_owners.clear()
                if (tool_uid := resolve_tool_call_uid(tool_uid_index, row['tool_call_id'])):
                    msg[TOOL_CALL_UID] = tool_uid
            if include_ancestors:
                skip, exact_clone_key = self._dedupe_replayed_user(messages, msg, exact_user_clones)
                if skip:
                    continue
                if exact_clone_key is not None:
                    exact_user_clones[exact_clone_key] = msg
            messages.append(msg)
        messages = _strip_stale_tool_call_markers(_strip_background_review_harness(messages))
        if repair_alternation and messages:
            _repair_replayed_conversation(messages, session_id)
        return messages

    @staticmethod
    def _canonical_replayed_user_content(msg: dict[str, Any]) -> tuple[Any, bool]:
        """Return canonical live content and whether *msg* is composite."""
        if msg.get('role') != 'user':
            return (None, False)
        handoff, live_view = split_user_originated_turn(msg)
        is_composite = handoff is not None and live_view is not None
        return (live_view.get('content') if is_composite else msg.get('content'), is_composite)

    @staticmethod
    def _exact_replayed_user_clone_key(timestamp: Any, content: Any) -> Optional[tuple[Any, str]]:
        """Return a hashable key for a column-exact rotation clone."""
        if timestamp is None or content in (None, '', []):
            return None
        try:
            return (timestamp, json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(',', ':')))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _find_duplicate_replayed_user_message(messages: list[dict[str, Any]], msg: dict[str, Any]) -> Optional[tuple[int, bool]]:
        """Adjacent replay duplicate ``(index, prefer_current)`` or None. Rotation may persist the current ask
        in the parent and again inside a composite child carrier: carriers compare by canonical live payload,
        ordinary users by exact string. The child carrier wins (it owns the durable row id and scaffold)."""
        if msg.get('role') != 'user':
            return None
        canonical = TranscriptCodec._canonical_replayed_user_content
        content, prefer_current = canonical(msg)
        if content in (None, '', []):
            return None
        for index in range(len(messages) - 1, -1, -1):
            prev = messages[index]
            if prev.get('role') == 'user':
                prev_content, prev_is_composite = canonical(prev)
                if prev_content == content and (prefer_current or prev_is_composite or isinstance(content, str)):
                    return (index, prefer_current)
            elif prev.get('role') == 'assistant' and (prev.get('content') or prev.get('tool_calls')):
                return None
        return None

    def _split_rewind_target(self, target_row: dict[str, Any], expected_target_content: Any, preserve_compaction_handoff: bool):
        """Validate an active rewind target; return its handoff scaffold (or None). ``ValueError``: inactive /
        non-user-originated / missing composite carrier; ``RuntimeError``: live payload changed."""
        if not target_row.get('active'):
            raise ValueError('rewind target is not active')
        handoff, live_view = split_user_originated_turn({**target_row, 'content': self._decode_content(target_row.get('content')), 'display_metadata': self._decode_display_metadata(target_row.get('display_metadata'))})
        if live_view is None:
            raise ValueError('rewind target is not a user-originated turn')
        live_content = live_view.get('content')
        if isinstance(live_content, str):
            live_content = sanitize_context(live_content).strip()
        if expected_target_content is not None and live_content != expected_target_content:
            raise RuntimeError('rewind target changed before it could be persisted')
        if preserve_compaction_handoff and handoff is None:
            raise ValueError('preserve_compaction_handoff requires an active composite carrier')
        return handoff if preserve_compaction_handoff else None

    def _is_explicit_fork_child_row(self, session: dict[str, Any], *, include_reset: bool=False) -> bool:
        """True when *session* is a branch, delegate, or tool child of its parent (``include_reset``: also a
        reset fork). Markers only count when they point at ``parent_session_id``: compression copies
        ``model_config`` onto the continuation, so presence-only matching would misclassify it (same binding
        as ``_NON_CONTINUATION_CHILD_FILTER_SQL``)."""
        if session.get('source') == 'tool':
            return True
        cfg = session.get('model_config')
        if isinstance(cfg, str):
            try:
                cfg = json.loads(cfg)
            except json.JSONDecodeError:
                return False
        if not isinstance(cfg, dict):
            return False
        markers = (cfg.get('_branched_from'), cfg.get('_delegate_from'))
        if include_reset:
            markers += (cfg.get('_reset_from'),)
        parent_id = session.get('parent_session_id')
        return parent_id in markers if parent_id else any(m is not None for m in markers)

from hermes_cli.timefmt import coerce_epoch

def _coerce_timestamp(value: Any, default: float) -> float:
    """Explicit message timestamp (datetime or number) or *default* when invalid or outside the sane
    epoch window — the write-side twin of the readers' ``coerce_epoch``: a bad row is never persisted."""
    result = coerce_epoch(value, field="message timestamp")
    if result is None:
        return default
    # SQLite reads both signed zero spellings back as 0.0. Hash the value
    # in that stored form so -0.0 and 0.0 retain the historical SQL/Python
    # identity equality.
    return 0.0 if result == 0.0 else result

def _tool_calls_count(tool_calls: Any) -> int:
    return 0 if tool_calls is None else (len(tool_calls) if isinstance(tool_calls, list) else 1)

def _tool_calls_len(raw: Any, scalar: int = 0) -> int:
    """Count of a stored ``tool_calls`` column: list length, *scalar* for a truthy non-list, else 0."""
    parsed = _parse_tool_calls(raw)
    return len(parsed) if isinstance(parsed, list) else (scalar if parsed else 0)


def _repair_replayed_conversation(messages, session_id):
    from agent.agent_runtime_helpers import repair_message_sequence
    repaired = repair_message_sequence(None, messages)
    if repaired:
        logger.info('Repaired %d message-alternation violation(s) while restoring session %s — durable transcript kept them, see repair_message_sequence', repaired, session_id)
