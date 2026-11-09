"""Pure SearchRules shared by native and PostgreSQL session persistence; no connections or storage lifecycle."""
from typing import Any, Collection
from hermes_state_common import MAX_FTS5_QUERY_CHARS
from typing import Optional
import re
_FTS5_SPECIAL_CHARS = '+{}():"^@/#&|~[]<>,;!?$=\\\''
_FTS5_SPECIAL_RE = re.compile(f'[{re.escape(_FTS5_SPECIAL_CHARS)}]')
_LIKE_TOKEN_RE = re.compile('"[^"]+"|\\S+')
_QUOTED_PHRASE_RE = re.compile('"[^"]*"')
_CJK_RANGES = ((19968, 40959), (13312, 19903), (131072, 173791), (12288, 12351), (12352, 12447), (12448, 12543), (44032, 55215))

def _is_cjk(cp: int) -> bool:
    return any((lo <= cp <= hi for lo, hi in _CJK_RANGES))

class SearchRules:
    _SEARCH_MESSAGE_RESULT_FIELDS = ('id', 'session_id', 'role', 'snippet', 'timestamp', 'tool_name', 'source', 'model', 'session_started', 'context')

    @classmethod
    def _search_message_fields(cls, fields: Optional[Collection[str]]) -> Optional[tuple[str, ...]]:
        """Validate and canonically order an optional result projection."""
        if fields is None:
            return None
        if isinstance(fields, str):
            raise TypeError('search fields must be a collection of field names, not a string')
        requested = set(fields)
        unknown = requested.difference(cls._SEARCH_MESSAGE_RESULT_FIELDS)
        if unknown:
            raise ValueError(f"unknown search result field(s): {', '.join(sorted(unknown))}")
        return tuple(field for field in cls._SEARCH_MESSAGE_RESULT_FIELDS if field in requested)

    @staticmethod
    def _sanitize_fts5_query(query: str) -> str:
        """Sanitize user input for FTS5 MATCH (raw special characters raise): preserve paired
        quoted phrases, strip unmatched special characters, and quote hyphenated/dotted
        terms so FTS5 matches them as phrases (``chat-send``, ``P2.2``, ``my-app.config.ts``)."""
        query = query[:MAX_FTS5_QUERY_CHARS]
        _quoted_parts: list = []

        def _hold(m: re.Match[str]) -> str:
            _quoted_parts.append(m.group(0))
            return f'\x00Q{len(_quoted_parts) - 1}\x00'
        sanitized = _QUOTED_PHRASE_RE.sub(_hold, query).replace('"', ' ')
        sanitized = _FTS5_SPECIAL_RE.sub(' ', sanitized)
        if '%' in sanitized and (not SearchRules._contains_cjk(sanitized)):
            sanitized = sanitized.replace('%', ' ')
        sanitized = re.sub('\\*+', '*', sanitized)
        sanitized = re.sub('(^|\\s)\\*', '\\1', sanitized)
        sanitized = re.sub('(?i)^(AND|OR|NOT)\\b\\s*', '', sanitized.strip())
        sanitized = re.sub('(?i)\\s+(AND|OR|NOT)\\s*$', '', sanitized.strip())
        sanitized = re.sub('\\b(\\w+(?:[._-]\\w+)+)\\b', '"\\1"', sanitized)
        for i, quoted in enumerate(_quoted_parts):
            sanitized = sanitized.replace(f'\x00Q{i}\x00', quoted)
        return sanitized.strip()

    @staticmethod
    def _contains_cjk(text: str) -> bool:
        return any(_is_cjk(ord(ch)) for ch in text)

    @staticmethod
    def _or_relaxed_query(query: str) -> Optional[str]:
        """The sanitized implicit-AND query rewritten as an any-term OR query, or ``None`` when
        relaxation does not apply: fewer than two searchable units (a single term cannot relax)
        or explicit ``OR``/``NOT`` (the caller expressed exact semantics). Quoted phrases stay
        whole units: ``"docker networking" tls`` -> ``"docker networking" OR tls``."""
        units: list[str] = []
        for raw_token in _LIKE_TOKEN_RE.findall(query):
            upper = raw_token.upper()
            if upper in {'OR', 'NOT'}:
                return None
            if upper != 'AND':
                units.append(raw_token)
        return ' OR '.join(units) if len(units) >= 2 else None

def search_sessions_by_id(list_sessions_rich, query: str, limit: int=20, include_archived: bool=True, source: str | None=None, sources: list[str] | None=None, exclude_sources: list[str] | None=None) -> list[dict[str, Any]]:
    """Search surfaced sessions by exact/prefix/substring session id. Also matches
        ``_lineage_root_id`` so an old compression root id resolves to the live continuation."""
    needle = (query or '').strip().lower()
    if not needle or limit <= 0:
        return []
    candidates = list_sessions_rich(source=source, sources=sources, exclude_sources=exclude_sources, limit=max(limit * 4, limit), offset=0, include_archived=include_archived, order_by_last_active=True, id_query=needle)

    def score(row: dict[str, Any]) -> int:
        normalized = [v.lower() for v in (str(row.get('id') or ''), str(row.get('_lineage_root_id') or '')) if v]
        if any(value == needle for value in normalized):
            return 0
        return 1 if any(value.startswith(needle) for value in normalized) else 2
    ranked = sorted(enumerate(candidates), key=lambda item: (score(item[1]), item[0]))
    return [row for _, row in ranked[:limit]]
