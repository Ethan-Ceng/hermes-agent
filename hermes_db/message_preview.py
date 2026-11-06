"""The bounded first-user preview projection written alongside each message."""

from agent.context_compressor import (
    LEGACY_SUMMARY_PREFIX, SUMMARY_PREFIX, _MERGED_PRIOR_CONTEXT_HEADER,
    _MERGED_SUMMARY_DELIMITER, _SUMMARY_END_MARKER,
)
from agent.skill_commands import AUTO_LOAD_SCAFFOLD_SQL_LIKE, SKILL_EXCERPT_JOINT, SKILL_SCAFFOLD_SQL_LIKE


def preview_text(row):
    content = row["content"]
    if row["role"] != "user" or content is None or row.get("display_kind") == "hidden":
        return None
    # SQLite's preview reads the encoded durable value, including the literal
    # reserved prefix of multimodal JSON. Model replay decodes it separately.
    text = content.decode("utf-8", "replace") if isinstance(content, bytes) else str(content)
    # SQLite's TEXT length/substr stop at NUL. Preserve that bounded display
    # projection while the durable BYTEA transcript keeps the entire payload.
    text = text.split("\x00", 1)[0]
    prefixes = (SUMMARY_PREFIX.split("Do NOT answer", 1)[0], LEGACY_SUMMARY_PREFIX)
    if text.lstrip("\t\n\r ").startswith(prefixes):
        if _SUMMARY_END_MARKER not in text:
            return None
        return _nonempty(text.split(_SUMMARY_END_MARKER, 1)[1])
    if _MERGED_SUMMARY_DELIMITER in text:
        prior, summary = text.split(_MERGED_SUMMARY_DELIMITER, 1)
        if summary.lstrip("\t\n\r ").startswith(prefixes):
            prior = prior.strip("\t\n\r ")
            if prior.startswith(_MERGED_PRIOR_CONTEXT_HEADER):
                prior = prior[len(_MERGED_PRIOR_CONTEXT_HEADER):].lstrip("\t\n\r ")
            return _nonempty(prior)
    flat = text.replace("\n", " ").replace("\r", " ")
    scaffold = text.lower().startswith((SKILL_SCAFFOLD_SQL_LIKE.rstrip("%").lower(),
                                       AUTO_LOAD_SCAFFOLD_SQL_LIKE.rstrip("%").lower()))
    if scaffold and len(text) > 800:
        return (flat[:400] + SKILL_EXCERPT_JOINT + flat[-400:]).encode("utf-8")
    return flat[:800 if scaffold else 63].encode("utf-8")


def _nonempty(text):
    return text.encode("utf-8") if text.strip("\t\n\r ") else None


def roster_preview(row):
    if row["role"] not in ("user", "assistant") or row.get("content") is None:
        return None
    text = " ".join(str(row["content"] or "").split()).strip()
    if not text:
        return None
    return (text[:80] + "..." if len(text) > 80 else text).encode("utf-8")
