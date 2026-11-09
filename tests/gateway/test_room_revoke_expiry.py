"""Unreadable unsigned horizons preserve grants for a finite recovery window."""

import base64
import json
import math
import pytest
from gateway import hosted_rooms as rooms
from gateway.hosted_room_peer import room_grant_hard_expiry, MAX_STATUS_GRANT_TTL_SECONDS


@pytest.mark.parametrize('expiry', [float('nan'), float('inf'), float('-inf')])
def test_unreadable_horizon_is_retained_until_bounded_deadline(tmp_path, expiry):
    now = 100.0
    claims = json.dumps({'expires_at': 101, 'status_expires_at': str(expiry)}).encode('ascii')
    token = base64.urlsafe_b64encode(claims).decode('ascii').rstrip('=') + '.eA'
    parsed = room_grant_hard_expiry(token, now=now)
    assert math.isfinite(parsed) and parsed == now + MAX_STATUS_GRANT_TTL_SECONDS
    location = tmp_path / 'rooms.db'
    rooms.create_room(location, room_id='room', name='Room', members=[{'profile': 'ops', 'handle': 'ops'}], authority_gateway_id='owner')
    rooms.hold_room_grant_revoke(location, room_id='room', member_id='ops', target_url='http://127.0.0.1:9121',
                                 grant=token, expires_at=expiry, now=now)
    assert rooms.held_room_grant_revokes(location, room_id='room', now=now)
    assert rooms.held_room_grant_revokes(location, room_id='room', now=now + rooms.MAX_OWED_REVOKE_SECONDS + 1) == []
    assert not rooms.owes_room_grant_revokes(location)
