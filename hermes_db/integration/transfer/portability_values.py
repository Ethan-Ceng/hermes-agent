"""Pure ImportValues shared by native and PostgreSQL session persistence; no connections or storage lifecycle."""
from hermes_cli.timefmt import coerce_epoch
import json
from typing import Optional
from typing import Any
import math
_IMPORT_SESSION_TEXT_FIELDS = ('source', 'user_id', 'model', 'system_prompt', 'end_reason', 'cwd', 'git_branch', 'git_repo_root', 'billing_provider', 'billing_base_url', 'billing_mode', 'cost_status', 'cost_source', 'pricing_version', 'title')
_IMPORT_MESSAGE_TEXT_FIELDS = ('tool_call_id', 'tool_name', 'effect_disposition', 'finish_reason', 'reasoning', 'reasoning_content', 'platform_message_id', 'message_id')
_IMPORT_MESSAGE_JSON_FIELDS = ('reasoning_details', 'codex_reasoning_items', 'codex_message_items', 'absorbed_message_uids', 'tool_call_uids')
_IMPORT_INT_COLS = ('input_tokens', 'output_tokens', 'cache_read_tokens', 'cache_write_tokens', 'reasoning_tokens', 'api_call_count')
_IMPORT_FLOAT_COLS = ('ended_at', 'estimated_cost_usd', 'actual_cost_usd')

class ImportValues:
    _IMPORT_MAX_SESSIONS, _IMPORT_MAX_MESSAGES_PER_SESSION, _IMPORT_MAX_TOTAL_MESSAGES = (500, 10000, 50000)
    _IMPORT_MAX_SESSION_BYTES, _IMPORT_MAX_TOTAL_BYTES = (5 * 1024 * 1024, 25 * 1024 * 1024)
    _SQLITE_INT_MIN, _SQLITE_INT_MAX = (-(1 << 63), (1 << 63) - 1)

    @staticmethod
    def _import_text_or_none(value: Any, field: str) -> Optional[str]:
        if value is None or isinstance(value, str):
            return value
        raise ValueError(f'{field} must be a string')

    @staticmethod
    def _import_int_or_none(value: Any, field: str) -> Optional[int]:
        try:
            return None if value is None else int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f'{field} must be an integer') from exc

    @staticmethod
    def _import_non_finite_path(value: Any, path: str) -> Optional[str]:
        """First ``path`` of a NaN/inf number anywhere in decoded JSON data, else None.

        Iterative walk (a recursive visitor would overflow on crafted nesting); cycles
        can't arrive through ``json.loads`` but guard anyway.
        """
        pending = [(value, path)]
        while pending:
            current, current_path = pending.pop()
            if isinstance(current, float) and (not math.isfinite(current)):
                return current_path
            if isinstance(current, dict):
                pending.extend(((child, f'{current_path}.{key}') for key, child in current.items()))
            elif isinstance(current, list):
                pending.extend(((child, f'{current_path}[{key}]') for key, child in enumerate(current)))
        return None

    @classmethod
    def _import_load_json(cls, value: str, path: str) -> Any:
        """``json.loads`` that refuses NaN/Infinity anywhere in the decoded value.

        A JSON exponent like ``1e309`` decodes to ``float("inf")``, which strict
        serializers reject and cost analytics mis-handle. Callers that intentionally
        decode a JSON-backed column (model_config, reasoning items) re-check through
        here so non-finite values can't reappear after the outer payload was inspected.
        """
        parsed = json.loads(value)
        non_finite = cls._import_non_finite_path(parsed, path)
        if non_finite is not None:
            raise ValueError(f'non-finite number at {non_finite}')
        return parsed

    @classmethod
    def _import_json_object_or_none(cls, value: Any, field: str) -> Optional[str]:
        if value is None:
            return None
        path = f'session.{field}'
        if isinstance(value, str):
            try:
                parsed = cls._import_load_json(value, path)
            except json.JSONDecodeError as exc:
                raise ValueError(f'{field} must be valid JSON') from exc
            if not isinstance(parsed, dict):
                raise ValueError(f'{field} must be a JSON object')
            return value
        if not isinstance(value, dict):
            raise ValueError(f'{field} must be a JSON object')
        if cls._import_non_finite_path(value, path) is not None:
            raise ValueError(f'non-finite number at {path}')
        try:
            return json.dumps(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f'{field} must be JSON serializable') from exc

    @staticmethod
    def _coerce_or(value: Any, cast, default):
        """``cast(value)``; *default* for None or an unparsable value."""
        try:
            return default if value is None else cast(value)
        except (TypeError, ValueError):
            return default

    @classmethod
    def _import_int_or_bounded(cls, value: Any, field: str, default: int) -> int:
        """Import an int column: SQL-int-range or *default* (never fails the import)."""
        number = cls._coerce_or(value, int, default)
        if number is None:
            return default
        if isinstance(number, bool) or not cls._SQLITE_INT_MIN <= number <= cls._SQLITE_INT_MAX:
            return default
        return number

    def _normalize_import_message(self, message: dict[str, Any], message_index: int) -> dict[str, Any]:
        """Type-check one payload message; raises ValueError naming the offending field."""
        clean_message = dict(message)
        role = clean_message.get('role')
        if not isinstance(role, str) or not role:
            raise ValueError(f'messages[{message_index}].role must be a non-empty string')
        for field in _IMPORT_MESSAGE_TEXT_FIELDS:
            clean_message[field] = self._import_text_or_none(clean_message.get(field), field)
        token_count = self._import_int_or_none(clean_message.get('token_count'), 'token_count')
        if token_count is not None and (not self._SQLITE_INT_MIN <= token_count <= self._SQLITE_INT_MAX):
            raise ValueError("token_count is outside SQLite's integer range")
        clean_message['token_count'] = token_count
        message_path = f'session.messages[{message_index}]'
        timestamp = clean_message.get('timestamp')
        if timestamp is not None and coerce_epoch(timestamp, field='messages[].timestamp') is None:
            raise ValueError(f'{message_path}.timestamp must be a supported Unix timestamp')
        self._validate_import_message_content(clean_message.get('content'), message_path)
        for field in _IMPORT_MESSAGE_JSON_FIELDS:
            json_value = clean_message.get(field)
            if isinstance(json_value, str):
                try:
                    self._import_load_json(json_value, f'{message_path}.{field}')
                except json.JSONDecodeError:
                    pass
                except ValueError:
                    raise
            elif json_value is not None:
                non_finite = self._import_non_finite_path(json_value, f'{message_path}.{field}')
                if non_finite is not None:
                    raise ValueError(f'non-finite number at {non_finite}')
        return clean_message

    @classmethod
    def _validate_import_message_content(cls, content: Any, message_path: str) -> None:
        """Scalar message content must be bindable and later serializable."""
        if isinstance(content, int) and (not isinstance(content, bool)) and (not cls._SQLITE_INT_MIN <= content <= cls._SQLITE_INT_MAX):
            raise ValueError(f"{message_path}.content is outside SQLite's integer range")
        if isinstance(content, float) and (not math.isfinite(content)):
            raise ValueError(f'non-finite number at {message_path}.content')
        if isinstance(content, (bytes, bytearray)):
            raise ValueError(f'{message_path}.content must be a string, list, object, finite number, or null')

    @classmethod
    def _import_float_or_finite(cls, value: Any, field: str) -> Optional[float]:
        """Import a float column: finite float or None (never fails the import).

        A JSON exponent like ``1e309`` decodes to ``float("inf")``; persisted, it later
        breaks strict JSON serialization in the session APIs. Missing stays missing.
        """
        if value is None:
            return None
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        return number if math.isfinite(number) else None

    def _normalize_import_session(self, raw: dict[str, Any], session_id: str, messages: list) -> dict[str, Any]:
        """Type-check one payload session + its messages; raises ValueError."""
        clean_session = dict(raw)
        clean_session['id'] = session_id
        clean_session['model_config'] = self._import_json_object_or_none(clean_session.get('model_config'), 'model_config')
        for field in ('parent_session_id', *_IMPORT_SESSION_TEXT_FIELDS):
            clean_session[field] = self._import_text_or_none(clean_session.get(field), field)
        started_at = clean_session.get('started_at')
        if started_at is not None and coerce_epoch(started_at, field='started_at') is None:
            raise ValueError('session.started_at must be a supported Unix timestamp')
        for field in _IMPORT_FLOAT_COLS:
            value = clean_session.get(field)
            if isinstance(value, float) and (not math.isfinite(value)):
                raise ValueError(f'non-finite number at session.{field}')
        for field in _IMPORT_INT_COLS:
            value = clean_session.get(field)
            if isinstance(value, int) and (not isinstance(value, bool)) and (not self._SQLITE_INT_MIN <= value <= self._SQLITE_INT_MAX):
                raise ValueError(f"{field} is outside SQLite's integer range")
        clean_messages: list[dict[str, Any]] = []
        for message_index, message in enumerate(messages):
            clean_messages.append(self._normalize_import_message(message, message_index))
        return {'session': clean_session, 'messages': clean_messages}

    def _validate_import_payload(self, sessions: list[dict[str, Any]]) -> tuple:
        """Size/shape/type validation of the whole payload; returns ``(normalized_items,
        errors)``. Every rejected entry is reported."""
        normalized: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        totals = {'messages': 0, 'bytes': 0}
        for index, raw in enumerate(sessions):
            session_id = str(raw.get('id') or '').strip() if isinstance(raw, dict) else ''
            try:
                item = self._validate_import_session(raw, session_id, seen_ids, totals)
            except ValueError as exc:
                item = {'index': index, 'error': str(exc)}
                if session_id:
                    item['session_id'] = session_id
                errors.append(item)
                continue
            seen_ids.add(session_id)
            normalized.append({'index': index, **item})
        return (normalized, errors)

    def _validate_import_session(self, raw: Any, session_id: str, seen_ids: set, totals: dict[str, int]) -> dict[str, Any]:
        """One payload session -> normalized item; ValueError(message) on rejection. *totals*
        accumulate before their limit check (a rejected oversize entry still counts)."""
        if not isinstance(raw, dict):
            raise ValueError('session must be an object')
        if not session_id:
            raise ValueError('session id is required')
        if session_id in seen_ids:
            raise ValueError('duplicate session id')
        messages = raw.get('messages') or []
        if not isinstance(messages, list):
            raise ValueError('messages must be a list')
        if len(messages) > self._IMPORT_MAX_MESSAGES_PER_SESSION:
            raise ValueError('messages exceeds the per-session import limit')
        if any(not isinstance(msg, dict) for msg in messages):
            raise ValueError('messages must contain only objects')
        try:
            measured = {k: v for k, v in raw.items() if k != 'timings'}
            session_bytes = len(json.dumps(measured, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))
        except (TypeError, ValueError):
            raise ValueError('session must be JSON serializable') from None
        if session_bytes > self._IMPORT_MAX_SESSION_BYTES:
            raise ValueError('session exceeds the import size limit')
        totals['bytes'] += session_bytes
        if totals['bytes'] > self._IMPORT_MAX_TOTAL_BYTES:
            raise ValueError('import exceeds the total size limit')
        item = self._normalize_import_session(raw, session_id, messages)
        totals['messages'] += len(item['messages'])
        if totals['messages'] > self._IMPORT_MAX_TOTAL_MESSAGES:
            raise ValueError('messages exceeds the total import limit')
        return item

values = ImportValues()
