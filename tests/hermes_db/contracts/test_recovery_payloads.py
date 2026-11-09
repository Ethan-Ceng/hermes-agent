"""Startup projections retain message bytes without parsing unrelated JSON text."""

import json


def test_webhook_recovery_preserves_nul_and_automation_presence(core_pair):
    from hermes_db.domains.runtime.postgres.store import PostgresRuntimeStore

    store, other = core_pair
    runtime = PostgresRuntimeStore(store)
    epoch = runtime.begin_epoch(instance_id='recovery-owner')
    expected = []
    for session_id, automation in [('absent', 'missing'), ('null', None), ('object', {}), ('false', False)]:
        store.create_session(session_id, 'webhook')
        native = {'source': {'platform': 'webhook', 'chat_id': 'signed-hook'}, 'text': 'before\x00after'}
        if automation != 'missing':
            native['automation'] = automation
        admitted = runtime.admit_input(epoch=epoch, session_id=session_id, principal_id='hook',
            request_id=session_id, payload={'native_text_v1': native})
        claim = runtime.claim_input(epoch=epoch, session_id=session_id)
        runtime.settle_input(epoch=epoch, admission_id=admitted['admission_id'],
            generation=claim['generation'], outcome='completed')
        if session_id in ('absent', 'null'):
            expected.append(admitted['admission_id'])
    payloads = runtime.webhook_payloads('signed-hook')
    assert len(payloads) == 2
    assert all(json.loads(row['payload_json'])['native_text_v1']['text'] == 'before\x00after' for row in payloads)
    assert {row['admission_id'] for row in runtime.webhook_finalizations()} == set(expected)
    assert runtime.webhook_payloads('other-chat') == []
    assert PostgresRuntimeStore(other).webhook_payloads('signed-hook') == []
    assert PostgresRuntimeStore(other).webhook_finalizations() == []


def test_webhook_recovery_scans_past_a_full_unrelated_batch(core_pair):
    from hermes_db.domains.runtime.postgres.store import PostgresRuntimeStore

    store, _ = core_pair
    runtime = PostgresRuntimeStore(store)
    epoch = runtime.begin_epoch(instance_id='paged-recovery')
    retained = {'native_text_v1': {'source': {'platform': 'webhook', 'chat_id': 'last'}, 'text': 'tail\x00body'}}
    for group in range(5):
        session_id = f'queue-{group}'
        store.create_session(session_id, 'webhook')
        for item in range(26):
            payload = retained if (group, item) == (4, 25) else {'native_text_v1': None}
            runtime.admit_input(epoch=epoch, session_id=session_id, principal_id='hook',
                request_id=f'input-{item}', payload=payload)
    assert [json.loads(row['payload_json']) for row in runtime.webhook_payloads('last')] == [retained]
