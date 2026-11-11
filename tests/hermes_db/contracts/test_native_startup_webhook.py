"""Native startup selectors and one-shot webhook finalization preserve owner fences."""

from dataclasses import replace


def test_native_webhook_delivery_queries_and_finalization_do_not_cross_stores(api_owner):
    from gateway.platforms.webhook_ingress import _committed, finalize_webhook
    from hermes_db.domains.runtime.authority import pending_target_ids
    from hermes_db.domains.runtime.access import runtime_for_store
    owner, db, other = api_owner
    runtime = runtime_for_store(db)
    db.create_session('hook', 'webhook')
    payload = {'native_text_v1': {'source': {'platform': 'webhook', 'chat_id': 'signed-hook'}}}
    admitted = runtime.admit_input(epoch=owner.epoch, session_id='hook', principal_id='hook', request_id='delivery', payload=payload)
    assert pending_target_ids(db, ('queued', 'unknown')) == {'hook'}
    assert pending_target_ids(other, ('queued', 'unknown')) == set()
    assert runtime.runtime_busy_reason() == 'admissions pending'
    assert _committed(owner, 'hook', 'delivery') == [{'admission_id': admitted['admission_id']}]
    assert len(runtime.webhook_payloads('signed-hook')) == 1
    assert runtime_for_store(other).webhook_payloads('signed-hook') == []
    claim = runtime.claim_input(epoch=owner.epoch, session_id='hook')
    terminal = runtime.settle_input(epoch=owner.epoch, admission_id=admitted['admission_id'],
        generation=claim['generation'], outcome='completed')
    receipt = owner._receipt(terminal)
    assert runtime.webhook_finalizations() == [{'admission_id': admitted['admission_id']}]
    assert not finalize_webhook(owner, replace(receipt, execution_generation=claim['generation'] + 1))
    assert finalize_webhook(owner, receipt)
    assert not finalize_webhook(owner, receipt)
    assert db.get_session('hook')['end_reason'] == 'webhook_complete'
    assert runtime.webhook_finalizations() == []
    assert runtime.runtime_busy_reason() is None


def test_native_webhook_pending_successor_and_stale_epoch_refuse_closure(api_owner):
    from gateway.platforms.webhook_ingress import finalize_webhook
    from hermes_db.domains.runtime.access import runtime_for_store
    owner, db, _ = api_owner
    runtime = runtime_for_store(db)
    db.create_session('hook', 'webhook')
    admitted = runtime.admit_input(epoch=owner.epoch, session_id='hook', principal_id='hook', request_id='one', payload={})
    claim = runtime.claim_input(epoch=owner.epoch, session_id='hook')
    terminal = runtime.settle_input(epoch=owner.epoch, admission_id=admitted['admission_id'], generation=claim['generation'], outcome='completed')
    receipt = owner._receipt(terminal)
    runtime.admit_input(epoch=owner.epoch, session_id='hook', principal_id='hook', request_id='two', payload={})
    assert not finalize_webhook(owner, receipt)
    runtime.begin_epoch(instance_id='replacement')
    assert not finalize_webhook(owner, receipt)
    assert db.get_session('hook')['ended_at'] is None
