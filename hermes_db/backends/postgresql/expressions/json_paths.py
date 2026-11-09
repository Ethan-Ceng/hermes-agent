"""Read the existing dotted/quoted-key and array-index configuration paths in Python."""

import json
import re

_PART = re.compile(r'\.(?:"((?:[^"\\]|\\.)*)"|([^.[\]"]+))|\[(#(?:-\d+)?|-?\d+)\]')


def _parts(path):
    position = 0
    for match in _PART.finditer('.' + path):
        if match.start() != position:
            raise ValueError('Invalid configuration JSON path')
        quoted, key, index = match.groups()
        if index is None:
            yield 'key', json.loads('"' + quoted + '"') if quoted is not None else key
        elif index.startswith('#'):
            yield 'end', int(index[2:]) if index.startswith('#-') else 0
        else:
            yield 'index', int(index)
        position = match.end()
    if position != len(path) + 1:
        raise ValueError('Invalid configuration JSON path')


def path_value(value, path):
    for kind, part in _parts(path):
        if kind == 'key':
            value = value.get(part) if isinstance(value, dict) else None
        elif isinstance(value, list):
            index = len(value) - part if kind == 'end' else part
            value = value[index] if -len(value) <= index < len(value) else None
        else:
            value = None
    return value
