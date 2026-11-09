"""Configuration selectors parse paths without normalizing stored JSON."""

import pytest

from hermes_db.backends.postgresql.expressions.json_paths import path_value


@pytest.mark.parametrize('path,expected', [('nested.value', 0), ('array[0]', False),
    ('array[#-1]', 'last'), ('array[#]', None), ('array[9]', None),
    ('"a.b"."quoted\\"key"', 'before\x00after'), ('nested.absent', None), ('array[0].absent', None)])
def test_configuration_json_path_values(path, expected):
    value = {'nested': {'value': 0}, 'array': [False, 'last'], 'a.b': {'quoted"key': 'before\x00after'}}
    assert path_value(value, path) == expected


@pytest.mark.parametrize('path', ['a..b', 'a[bad]', 'a[0', ''])
def test_invalid_configuration_path_is_explicit(path):
    with pytest.raises(ValueError, match='JSON path'):
        path_value({}, path)
