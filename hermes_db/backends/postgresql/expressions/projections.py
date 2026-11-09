"""Opaque JSON values become ASCII comparison tokens, never lossy text replacements."""

import json


def query_token(value):
    return None if value is None else json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(',', ':'))


def query_key(key):
    return query_token(key).encode('ascii').hex()


def display_projection(raw):
    metadata = json.loads(raw) if isinstance(raw, str) else raw
    return {query_key(key): query_token(value) for key, value in (metadata or {}).items()}


def display_value(column, key):
    return column.table.c.display_query[query_key(key)].as_string()
