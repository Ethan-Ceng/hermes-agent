"""Merged transcript and room semantics must work on the real PG backend."""
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def test_transcript_snapshot_pins_public_reads_without_crossing_profile(pg_pair):
    owner, peer = pg_pair
    for store, content in ((owner, "owner first"), (peer, "peer only")):
        store.create_session("same", "cli")
        store.append_message("same", "user", content)
    with owner.transcript_read_snapshot() as consistent:
        assert [row["content"] for row in owner.get_messages("same")] == ["owner first"]
        assert owner.get_session("same")["message_count"] == 1
        owner.append_message("same", "assistant", "owner committed")
        assert [row["content"] for row in owner.get_messages("same")] == ["owner first"]
        assert owner.get_session("same")["message_count"] == 1
        with owner.transcript_read_snapshot() as nested:
            assert nested() and consistent() and nested.pinned
        assert [row["content"] for row in peer.get_messages("same")] == ["peer only"]
    assert [row["content"] for row in owner.get_messages("same")] == ["owner first", "owner committed"]
    from hermes_db.integration.session_composition import create_session_store
    reopened = create_session_store(owner._transactions, owner.scope)
    try:
        assert reopened.get_session("same")["message_count"] == 2
        assert [row["content"] for row in reopened.get_messages("same")] == ["owner first", "owner committed"]
    finally:
        reopened.close()


def test_transcript_cursor_ignores_append_but_observes_display_rewrite(pg_store):
    pg_store.create_session("s", "cli")
    first = pg_store.append_message("s", "user", "first")
    before = pg_store.transcript_cursor_state("s", first)
    pg_store.append_message("s", "assistant", "new tail")
    assert pg_store.transcript_cursor_state("s", first) == before
    assert pg_store.set_user_message_content("s", first, "edited") == 1
    assert pg_store.transcript_cursor_state("s", first) != before
    assert pg_store.get_messages("s")[0]["content"] == "edited"


def test_deferred_room_reopens_same_generation_and_resets_deadline(pg_profiles):
    from gateway import hosted_rooms as rooms
    from gateway import hosted_room_driver as driver
    from tests.gateway.test_hosted_room_driver import FakeClock, _admit, _identity, _lease
    with pg_profiles("one"):
        location = rooms.default_db_path()
        rooms.create_room(location, room_id="room-1", name="merged room",
                          members=[{"profile": "ops", "handle": "ops"}], authority_gateway_id="gateway-a", now=90)
        clock = FakeClock()
        identity = _identity()
        lease = _lease(location, clock, ttl=60)
        _admit(location, identity, clock)
        attempt = driver.start_task(location, identity, lease, expected_cancel_generation=0, clock=clock)
        driver.mark_attempt_indeterminate(location, attempt, lease, clock=clock)
        driver.defer_indeterminate_task(location, identity, lease, expected_execution_generation=attempt.execution_generation,
            expected_cancel_generation=attempt.cancel_generation, reason="peer_not_ready", clock=clock)
        clock.advance(7)
        resumed = driver.reopen_deferred_task(location, identity, lease,
            expected_execution_generation=attempt.execution_generation,
            expected_cancel_generation=attempt.cancel_generation, clock=clock)
        assert resumed["status"] == "indeterminate"
        assert resumed["execution_generation"] == attempt.execution_generation
        assert resumed["cancel_generation"] == attempt.cancel_generation
        assert resumed["started_at"] == clock()
        with pg_profiles("two"):
            assert driver.list_tasks(rooms.default_db_path(), room_id="room-1") == []


def test_history_binding_owner_equivalence_keeps_store_namespace(pg_pair):
    import json
    from gateway.owner_identity import host_owner_subject
    from hermes_db.domains.sessions.postgres.queries.mutation_binding import bindings_agree
    owner, peer = pg_pair
    current = json.dumps(["store:" + owner.scope.store_id, host_owner_subject()])
    login = json.dumps(["store:" + owner.scope.store_id, "basic:previous-login"])
    foreign = json.dumps(["store:" + peer.scope.store_id, host_owner_subject()])
    assert bindings_agree(current, login, owner.scope, ownership=owner._context.ownership)
    assert not bindings_agree(current, foreign, owner.scope, ownership=owner._context.ownership)
    assert not bindings_agree(foreign, foreign, owner.scope, ownership=owner._context.ownership)
    assert bindings_agree(None, None, owner.scope, ownership=owner._context.ownership)
    assert not bindings_agree(None, current, owner.scope, ownership=owner._context.ownership)


def test_user_content_metadata_patch_preserves_reactions_and_removes_null_keys(pg_store):
    pg_store.create_session("s", "cli")
    row_id = pg_store.append_message("s", "user", "before", display_metadata={
        "reactions": {"ok": 1}, "drop": "old", "nested": {"keep": 1, "drop": 2}})
    assert pg_store.set_user_message_content("s", row_id, "after", display_metadata={
        "drop": None, "nested": {"drop": None, "added": 3}}) == 1
    row = pg_store.get_messages("s")[0]
    assert row["content"] == "after"
    assert row["display_metadata"] == {"reactions": {"ok": 1}, "nested": {"keep": 1, "added": 3}}


def test_gateway_transcript_pages_poll_and_reset_on_real_pg(pg_pair):
    from gateway.session_stored_reads import read_transcript, _decode_cursor
    owner, peer = pg_pair
    for store, body in ((owner, 'one'), (peer, 'peer secret')):
        store.create_session('s', 'cli')
        store.append_message('s', 'user', body)
    owner.append_message('s', 'assistant', 'two')
    binding = ('s', None, 'oldest')
    def page(held=None):
        return read_transcript(owner, 's', ['s'], binding, held, 1,
                               profile_home=owner.scope.profile_home, inline_images=False)
    first = page()
    assert first['reset'] and [row['text'] for row in first['rows']] == ['one']
    owner.append_message('s', 'user', 'three\x00tail')
    second = page(_decode_cursor(first['next_cursor'], binding))
    assert not second['reset'] and [row['text'] for row in second['rows']] == ['two']
    third = page(_decode_cursor(second['next_cursor'], binding))
    assert not third['reset'] and [row['text'] for row in third['rows']] == ['three\x00tail']
    assert page(_decode_cursor(third['next_cursor'], binding))['rows'] == []
    row_id = owner.get_messages('s')[0]['id']
    owner.set_user_message_content('s', row_id, 'edited')
    reset = page(_decode_cursor(third['next_cursor'], binding))
    assert reset['reset'] and [row['text'] for row in reset['rows']] == ['edited']
    assert [row['content'] for row in peer.get_messages('s')] == ['peer secret']


def test_workspace_picker_filters_before_limit_and_scopes_facts(pg_pair):
    owner, peer = pg_pair
    for store in (owner, peer):
        store.create_session('match', 'cli', cwd='/repo/sub', git_repo_root='/repo')
        store.append_message('match', 'user', 'question')
        store.append_message('match', 'assistant', 'answer')
    owner.create_session('other', 'cli', cwd='/unrelated')
    owner.append_message('other', 'user', 'more recent')
    assert [row['id'] for row in owner.list_sessions_rich(workspace_key='/repo/', limit=1)] == ['match']
    assert owner.sessions_in_workspace(['match', 'other'], '/repo/') == {'match'}
    roots, unlisted, replies = owner.picker_session_facts(['match'], ['match'], ['match'])
    assert roots['match']['git_repo_root'] == '/repo'
    assert unlisted['match']['_preview_raw'] == 'question'
    assert replies['match'] == [('answer', False)]
    assert owner.session_current_segments(['match', 'absent']) == {'match': 'match'}


def test_explicit_archive_retires_visible_reaped_bot_chat(pg_store):
    pg_store.create_session('bot', 'cli')
    assert pg_store.set_session_title('bot', 'Bot Chat')
    pg_store.end_session('bot', 'agent_close')
    assert pg_store.set_session_archived('bot', True)
    row = pg_store.get_session('bot')
    assert row['archived'] and not row['hidden'] and row['title'] is None
    assert row['end_reason'] is None and row['ended_at'] is not None
    assert pg_store.resolve_session_by_title('Bot Chat') is None
    assert pg_store.set_session_archived('bot', True)
    assert pg_store.set_session_archived('bot', False)
    assert not pg_store.get_session('bot')['archived']


def test_refused_turn_keeps_display_and_reopens_without_model_input(pg_pair):
    from hermes_db.integration.session_composition import create_session_store
    owner, peer = pg_pair
    for store in (owner, peer):
        store.create_session('s', 'cli')
    owner.append_message('s', 'user', 'accepted')
    owner.append_message('s', 'assistant', 'answer')
    boundary = owner.append_message('s', 'user', 'refused', display_metadata={'reactions': {'ok': 1}})
    owner.append_message('s', 'assistant', 'refusal')
    owner.append_message('s', 'user', 'late steer')
    assert owner.retain_refused_turn_for_display('s', notice='try again', boundary_row_id=boundary)
    reopened = create_session_store(owner._transactions, owner.scope)
    try:
        assert [row['content'] for row in reopened.get_messages('s')] == ['accepted', 'answer']
        shown = reopened.get_messages('s', include_compacted=True)
        assert [row['content'] for row in shown] == ['accepted', 'answer', 'refused']
        assert shown[-1]['display_kind'] == 'content_refused'
        assert shown[-1]['display_metadata']['reactions'] == {'ok': 1}
        assert peer.get_messages('s') == []
    finally:
        reopened.close()


def test_worker_tool_root_and_marked_delegate_reads(pg_store):
    from hermes_db.domains.runtime.postgres.operations.worker_compression_reads import lineage
    from hermes_state_delegate_children import delegate_descendant_ids
    from tools.delegate_tool_sessions import stored_child_session
    pg_store.create_session('parent', 'cli')
    cfg = {'_delegate_from': 'parent', '_subagent_id': 'child-key'}
    pg_store.create_session('child', 'subagent', parent_session_id='parent', model_config=cfg)
    assert delegate_descendant_ids(pg_store, 'parent') == ['child']
    assert delegate_descendant_ids(pg_store, 'child') == []
    assert stored_child_session(pg_store, 'child-key', ['parent']) == 'child'
    pg_store.create_session('tool', 'tool', parent_session_id='parent')
    pg_store.end_session('tool', 'compression')
    pg_store.create_session('rotated', 'tool', parent_session_id='tool')
    assert pg_store.get_tool_rotation_root('rotated') == 'tool'
    with pg_store._read() as conn:
        assert lineage(conn, pg_store.scope, 'rotated', {'target': 'rotated'})['tool_root'] == 'tool'


def test_refusal_fallback_releases_checkout_for_one_connection_pool(pg_store, postgres_test_config):
    from dataclasses import replace
    from hermes_db.infra.backends.postgresql.engine import get_engine
    from hermes_db.infra.backends.postgresql.transactions import Transactions
    from hermes_db.tables.metadata import SCHEMA
    from hermes_db.integration.session_composition import create_session_store
    settings = replace(postgres_test_config.settings, pool_size=1, max_overflow=0,
                       connection_budget=1, pool_timeout_seconds=1)
    engine = get_engine(settings)
    store = create_session_store(Transactions(engine, pg_store._transactions.schema, schema_token=SCHEMA), pg_store.scope)
    try:
        store.create_session('fallback', 'cli')
        store.append_message('fallback', 'user', 'no boundary available')
        store.append_message('fallback', 'assistant', 'refusal')
        assert store.retain_refused_turn_for_display('fallback', notice='retry')
        assert store.get_messages('fallback') == []
        assert store.get_messages('fallback', include_compacted=True)[0]['content'] == 'no boundary available'
    finally:
        store.close()
        engine.dispose()


def test_display_identity_read_does_not_load_removed_bodies(pg_store):
    pg_store.create_session('s', 'cli')
    pg_store.append_message('s', 'user', 'kept')
    pg_store.append_message('s', 'assistant', 'answer')
    removed = pg_store.append_message('s', 'user', 'large removed body' * 10000)
    pg_store.rewind_to_message('s', removed)
    rows = pg_store._fetch_conversation_rows(['s'], '', with_session_id=False, with_compacted=True)
    assert next(row for row in rows if row['id'] == removed)['content'] is None
    assert [row['content'] for row in pg_store.get_messages_as_conversation('s', include_compacted=True)] == ['kept', 'answer']


def test_worker_user_content_merges_metadata_on_receipt_connection(pg_store, pg_runtime):
    from tests.hermes_db.contracts.test_worker_metadata import _worker
    call = _worker(pg_store, pg_runtime)
    row_id = call('transcript.append', {'messages': [{'role': 'user', 'content': 'before',
        'display_metadata': {'reactions': {'ok': 1}, 'drop': 2}}]})['annotations'][0]['_row_id']
    assert call('session.user_content', {'row_id': row_id, 'content': 'after',
        'display_metadata': {'drop': None, 'new': 3}}) == {'value': 1}
    assert pg_store.get_messages('s')[0]['display_metadata'] == {'reactions': {'ok': 1}, 'new': 3}


def test_runtime_archive_retires_bot_but_bulk_leaves_it_available(pg_store, pg_runtime):
    import time
    for sid in ('bot', 'ordinary'):
        pg_store.create_session(sid, 'cli')
        pg_store.append_message(sid, 'user', 'history')
        pg_store.end_session(sid, 'agent_close')
    pg_store.set_session_title('bot', 'Bot Chat')
    assert pg_store.archive_sessions(started_before=time.time() + 100) == 1
    assert not pg_store.get_session('bot')['archived']
    epoch = pg_runtime.begin_epoch(instance_id='owner')
    args = dict(epoch=epoch, principal_id='owner', session_id='bot', request_id='archive-bot',
                expected_revision=0, operation='archive', payload={'archived': True})
    first = pg_runtime.mutate_session(**args)
    assert pg_runtime.mutate_session(**args) == first
    assert pg_store.get_session('bot')['title'] is None
    assert pg_store.get_session('bot')['end_reason'] is None
    assert pg_store.get_session_by_title('Bot Chat') is None


def test_telegram_topic_binding_cas_cannot_overwrite_newer_or_cleared_link(pg_pair):
    owner, peer = pg_pair
    fields = dict(chat_id='chat', thread_id='topic', user_id='user', session_key='route')
    for store in (owner, peer):
        store.create_session('old', 'telegram')
        store.create_session('new', 'telegram')
        assert store.bind_telegram_topic(**fields, session_id='old', expected_session_id=None)
    assert owner.bind_telegram_topic(**fields, session_id='new', expected_session_id='old')
    assert not owner.bind_telegram_topic(**fields, session_id='old', expected_session_id='old')
    assert owner.get_telegram_topic_binding(chat_id='chat', thread_id='topic')['session_id'] == 'new'
    assert peer.get_telegram_topic_binding(chat_id='chat', thread_id='topic')['session_id'] == 'old'
    owner.delete_telegram_topic_binding(chat_id='chat', thread_id='topic')
    assert not owner.bind_telegram_topic(**fields, session_id='old', expected_session_id='new')
    assert owner.get_telegram_topic_binding(chat_id='chat', thread_id='topic') is None


def test_rotated_transcript_reads_handoffs_and_resets_held_cursor(pg_store):
    from gateway.session_stored_reads import read_transcript, _decode_cursor
    from tests.gateway.test_session_stored_reads import _summary
    pg_store.create_session('parent', 'cli')
    pg_store.append_message('parent', 'user', 'question 1')
    pg_store.append_message('parent', 'assistant', 'answer 1')
    binding = ('parent', None, 'oldest')
    before = read_transcript(pg_store, 'parent', ['parent'], binding, None, 20,
        profile_home=pg_store.scope.profile_home, inline_images=False)
    pg_store.publish_compression_child(parent_session_id='parent', child_session_id='child', source='cli',
        messages=[{'role': 'user', 'content': _summary('## Goal\nship it', 2), '_compressed_summary': True}],
        require_compression_lease=False)
    pg_store.append_message('child', 'user', 'question 2')
    after = read_transcript(pg_store, 'child', ['parent', 'child'], binding,
        _decode_cursor(before['next_cursor'], binding), 20, profile_home=pg_store.scope.profile_home, inline_images=False)
    assert after['reset']
    assert any(row['row_kind'] == 'compaction' for row in after['rows'])
    assert [row['text'] for row in after['rows'] if row['row_kind'] == 'message'] == ['question 1', 'answer 1', 'question 2']
