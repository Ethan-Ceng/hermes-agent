"""Derived query markers do not invalidate a prepared current-store move."""

import pytest

from hermes_db.integration.transfer.move_values import recipient_snapshot_digest, snapshot_digest


@pytest.mark.parametrize('recipient', [False, True])
def test_model_marker_backfill_keeps_move_content_fingerprint(recipient):
    before = {'session': {'id': 's', 'model_config': '{"_delegate_from":"owner"}'},
        'system_prompt': b'exact\x00prompt', 'tool_pin': None, 'messages': [{'content': 'body'}], 'usage': []}
    after = {**before, 'session': {**before['session'], 'delegate_origin': b'owner',
        'has_delegate_marker': 1, 'has_branch_marker': 0}}
    def fingerprint(snapshot):
        return recipient_snapshot_digest(snapshot, 1) if recipient else snapshot_digest(snapshot)
    assert fingerprint(after) == fingerprint(before)
    changed = {**after, 'session': {**after['session'], 'model_config': '{"_delegate_from":"changed"}'}}
    assert fingerprint(changed) != fingerprint(before)
