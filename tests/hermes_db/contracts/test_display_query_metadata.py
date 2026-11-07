"""Admission presentation metadata remains opaque to transcript selectors."""


def test_admitted_nul_preview_keeps_display_reads_and_owner_lookup(store):
    from gateway.session_display import admit_display, display_turn_scope, worker_display_kwargs

    committed = admit_display({'title_preview': 'before\x00after'})['display_v1']
    with display_turn_scope('admission', committed):
        metadata = worker_display_kwargs()['persist_user_display_metadata']
    metadata['gateway_input_owner'] = 'owner'
    store.create_session('s', 'cli')
    row_id = store.append_message('s', 'user', 'body', display_metadata=metadata)
    assert store.display_message_count('s') == 1
    assert store.has_gateway_input_owner('s', 'owner')
    assert not store.has_gateway_input_owner('s', 'other')
    rows = store.get_messages('s', include_compacted=True)
    assert rows[0]['display_metadata']['title_preview'] == 'before\x00after'
    store.set_user_message_content('s', row_id, 'updated',
        display_metadata={**metadata, 'gateway_input_owner': r'owner\u0000'})
    assert not store.has_gateway_input_owner('s', 'owner')
    assert store.has_gateway_input_owner('s', r'owner\u0000')
    assert not store.has_gateway_input_owner('s', 'owner\x00')
