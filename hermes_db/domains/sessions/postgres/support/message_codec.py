"""Reuse the current pure transcript codec and projections without SQLite I/O.

Content has a new, unambiguous BYTEA envelope: text and arbitrary bytes have
different tags. No legacy disk format is read by the PostgreSQL backend.
"""
from hermes_db.domains.sessions.codec import TranscriptCodec
import math
codec = TranscriptCodec()
TEXT_COLUMNS = ('reasoning', 'reasoning_content', 'reasoning_details', 'codex_reasoning_items', 'codex_message_items', 'api_content')
INTERNAL_COLUMNS = ('store_id', 'search_content', 'preview_text', 'search_document', 'search_grams', 'spillover_names', 'roster_preview', 'display_query')

def content_to_bytes(value):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if isinstance(value, bytes):
        return b'B' + value
    if isinstance(value, bool):
        value = str(int(value))
    elif isinstance(value, float) and math.isinf(value):
        value = 'Inf' if value > 0 else '-Inf'
    return b'T' + str(value).encode('utf-8')

def content_from_bytes(value):
    if value is None:
        return None
    value = bytes(value)
    if value[:1] == b'B':
        return value[1:]
    if value[:1] != b'T':
        raise ValueError('Invalid message content envelope')
    return value[1:].decode('utf-8')

def stored_values(row):
    result = dict(row)
    result['content'] = content_to_bytes(result['content'])
    for column in TEXT_COLUMNS:
        value = result.get(column)
        if value is not None:
            result[column] = str(value).encode('utf-8')
    return result

def decoded_row(row):
    result = dict(row)
    result['content'] = content_from_bytes(result['content'])
    for column in TEXT_COLUMNS:
        value = result[column]
        if value is not None:
            result[column] = bytes(value).decode('utf-8')
    for column in INTERNAL_COLUMNS:
        result.pop(column, None)
    return result

def merge_display_metadata(current, patch):
    """Apply the user-content rewrite's JSON merge-patch without replacing reactions."""
    result = dict(current) if isinstance(current, dict) else {}
    for key, value in patch.items():
        if value is None:
            result.pop(key, None)
        elif isinstance(value, dict):
            result[key] = merge_display_metadata(result.get(key), value)
        else:
            result[key] = value
    return result
