"""Review regressions for recipient proofs and prepared transcript publication."""

import pytest

from hermes_state_runtime import RuntimeStoreError


@pytest.mark.parametrize('change', ['messages', 'prompt'])
def test_move_never_retires_source_after_recipient_snapshot_changes(core_pair, change):
    source, target = core_pair
    source.create_session('s', 'cli', system_prompt='original prompt')
    source.append_message('s', 'user', 'original body')
    payload = source.export_session_for_move('s')
    target.import_moved_session(payload, profile_name='target')
    mutations = {
        'messages': lambda: target.replace_messages('s', [{'role': 'user', 'content': 'other body'}]),
        'prompt': lambda: target.update_system_prompt('s', 'other prompt'),
    }
    mutations[change]()
    with pytest.raises(RuntimeStoreError, match='move_not_confirmed'):
        source.delete_moved_session('s')
    with pytest.raises(RuntimeStoreError, match='session_exists'):
        target.import_moved_session(payload, profile_name='target')
    assert source.get_messages('s')[0]['content'] == 'original body'
    assert source.get_session('s')['system_prompt'] == 'original prompt'






def test_move_allows_recipient_append_without_losing_imported_prefix(core_pair):
    source, target = core_pair
    source.create_session('s', 'cli')
    source.append_message('s', 'user', 'original')
    payload = source.export_session_for_move('s')
    target.import_moved_session(payload, profile_name='target')
    target.append_message('s', 'assistant', 'new recipient work')
    assert target.import_moved_session(payload, profile_name='target') == 'present'
    assert source.delete_moved_session('s')
    assert [row['content'] for row in target.get_messages('s')] == ['original', 'new recipient work']


@pytest.mark.parametrize('in_place', [True, False])
def test_prepared_compression_refuses_late_public_append(core_pair, in_place):
    from hermes_db.integration.runtime_composition import create_runtime_store
    from tests.hermes_db.contracts.test_prepared_mutations import local_setup
    db = core_pair[0]
    runtime = create_runtime_store(db)
    sid, _ = local_setup(db)
    db.append_message(sid, 'user', 'before preparation')
    epoch = runtime.begin_epoch(instance_id='owner')
    current = db.get_session(sid)
    args = dict(epoch=epoch, principal_id='human', session_id=sid, request_id='compress',
        expected_revision=current['runtime_revision'], expected_generation=current['runtime_generation'],
        operation='compress', payload={})
    prepared = dict(snapshot=runtime.mutate_session(**args, _prepare_only=True)['snapshot'], in_place=in_place,
                    messages=[{'role': 'user', 'content': 'summary'}])
    db.append_message(sid, 'assistant', 'late retained body')
    with pytest.raises(RuntimeStoreError, match='revision_conflict'):
        runtime.mutate_session(**args, _prepared=prepared)
    assert [row['content'] for row in db.get_messages(sid)] == ['before preparation', 'late retained body']
