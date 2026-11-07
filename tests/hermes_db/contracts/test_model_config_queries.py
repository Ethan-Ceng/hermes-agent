"""Opaque model options must not break unrelated session selectors."""

import pytest


@pytest.mark.parametrize('operation', ['key_scan', 'listing', 'deletion'])
def test_nul_model_option_does_not_break_session_queries(store, operation):
    store.create_session('configured', 'api_server', model_config={
        'browser_model_lock': {'model_options': {'extra_body': {'stop': ['\x00']}}}})
    if operation == 'key_scan':
        assert store.session_ids_with_model_config_key('browser_model_lock') == ['configured']
    elif operation == 'listing':
        assert [row['id'] for row in store.list_sessions_rich(include_children=False)] == ['configured']
    else:
        store.create_session('victim', 'cli')
        assert store.delete_session('victim') == 1
        assert store.get_session('configured') is not None


def test_model_marker_updates_keep_raw_options_and_listing_semantics(store):
    import json

    store.create_session('owner', 'cli')
    config = {'_delegate_from': 'owner', 'browser_model_lock': {'model_options': {'stop': ['\x00']}}}
    store.create_session('child', 'cli', model_config=config)
    assert 'child' not in {row['id'] for row in store.list_sessions_rich(include_children=False)}
    store.patch_session_model_config('child', {'_delegate_from': None})
    assert 'child' in {row['id'] for row in store.list_sessions_rich(include_children=False)}
    assert json.loads(store.get_session('child')['model_config'])['browser_model_lock'] == config['browser_model_lock']
    store.patch_session_model_config('child', {'_delegate_from': False})
    assert 'child' not in {row['id'] for row in store.list_sessions_rich(include_children=False)}
