"""Prepared transcript publication preserves late-append conflict detection."""

import pytest

from hermes_state_runtime import RuntimeStoreError










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
