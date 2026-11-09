"""Derived searchable document and indexed one/two-character substring candidates."""

import json
import re

from hermes_db.domains.sessions.postgres.support.message_codec import codec
from hermes_state_common import FTS_TOOL_CONTENT_PREFIX_CHARS


def content_text(row):
    value = codec._decode_content(row.get("content"))
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace").replace("\x00", "")
    return str(value).replace("\x00", "") if value is not None else ""


def short_grams(text):
    grams = set()
    for word in re.findall(r"[^\W_]+", text.casefold()):
        grams.update(word)
        grams.update(word[index:index + 2] for index in range(len(word) - 1))
    return sorted(grams)


def projection(row):
    content = content_text(row)
    if row.get("role") == "tool":
        content = content[:FTS_TOOL_CONTENT_PREFIX_CHARS]
    document = "\n".join(str(value) for value in (content, row.get("tool_name"), row.get("tool_calls")) if value).replace("\x00", "")
    return document, short_grams(document)
