"""Reuse the current pure transcript codec and projections without SQLite I/O.

Content has a new, unambiguous BYTEA envelope: text and arbitrary bytes have
different tags. No legacy disk format is read by the PostgreSQL backend.
"""

import math

from hermes_state_messages import SessionMessagesMixin


class MessageCodec:
    _CONTENT_JSON_PREFIX = "\x00json:"
    REACTIONS_METADATA_KEY = "reactions"
    _encode_content = classmethod(SessionMessagesMixin._encode_content.__func__)
    _decode_content = classmethod(SessionMessagesMixin._decode_content.__func__)
    _encode_display_metadata = staticmethod(SessionMessagesMixin._encode_display_metadata)
    _decode_display_metadata = staticmethod(SessionMessagesMixin._decode_display_metadata)
    _reasoning_json_text = staticmethod(SessionMessagesMixin._reasoning_json_text)
    _display_identity = staticmethod(SessionMessagesMixin._display_identity)
    _display_dedupe_key = SessionMessagesMixin._display_dedupe_key
    _is_model_only_row = SessionMessagesMixin._is_model_only_row
    _fold_summary_carrier = staticmethod(SessionMessagesMixin._fold_summary_carrier)
    _dedupe_display_generations = SessionMessagesMixin._dedupe_display_generations
    _message_row_params = SessionMessagesMixin._message_row_params
    _serialized_message_row = SessionMessagesMixin._serialized_message_row
    _decoded_repair_row = SessionMessagesMixin._decoded_repair_row
    _row_to_message_dict = SessionMessagesMixin._row_to_message_dict
    _stamp_tool_call_uids = staticmethod(SessionMessagesMixin._stamp_tool_call_uids)
    _loaded_view_content = staticmethod(SessionMessagesMixin._loaded_view_content)
    _rows_to_conversation = SessionMessagesMixin._rows_to_conversation
    _dedupe_replayed_user = SessionMessagesMixin._dedupe_replayed_user
    _canonical_replayed_user_content = staticmethod(SessionMessagesMixin._canonical_replayed_user_content)
    _exact_replayed_user_clone_key = staticmethod(SessionMessagesMixin._exact_replayed_user_clone_key)
    _find_duplicate_replayed_user_message = staticmethod(SessionMessagesMixin._find_duplicate_replayed_user_message)
    _split_rewind_target = SessionMessagesMixin._split_rewind_target
    _row_identity = classmethod(SessionMessagesMixin._row_identity.__func__)


codec = MessageCodec()
TEXT_COLUMNS = ("reasoning", "reasoning_content", "reasoning_details", "codex_reasoning_items", "codex_message_items", "api_content")
INTERNAL_COLUMNS = ("store_id", "search_content", "preview_text", "search_document", "search_grams", "spillover_names", "roster_preview", "display_query")


def content_to_bytes(value):
    if value is None or isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, bytes):
        return b"B" + value
    if isinstance(value, bool):
        value = str(int(value))
    elif isinstance(value, float) and math.isinf(value):
        value = "Inf" if value > 0 else "-Inf"
    return b"T" + str(value).encode("utf-8")


def content_from_bytes(value):
    if value is None:
        return None
    value = bytes(value)
    if value[:1] == b"B":
        return value[1:]
    if value[:1] != b"T":
        raise ValueError("Invalid message content envelope")
    return value[1:].decode("utf-8")


def stored_values(row):
    result = dict(row)
    result["content"] = content_to_bytes(result["content"])
    for column in TEXT_COLUMNS:
        value = result.get(column)
        if value is not None:
            result[column] = str(value).encode("utf-8")
    return result


def decoded_row(row):
    result = dict(row)
    result["content"] = content_from_bytes(result["content"])
    for column in TEXT_COLUMNS:
        value = result[column]
        if value is not None:
            result[column] = bytes(value).decode("utf-8")
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
