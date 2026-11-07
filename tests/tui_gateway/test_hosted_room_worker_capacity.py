"""Deadline expiry releases a real worker slot without racing the runner's clock."""

from types import SimpleNamespace

from gateway import hosted_room_driver as state, hosted_rooms
from tests.tui_gateway.test_hosted_room_driver_runtime import (
    PROFILE, FakeSessionRPC, RecordingTurnLocks, _wait_for,
)
from tui_gateway import hosted_room_driver as driver


def test_deadline_releases_worker_capacity_for_later_room(tmp_path, monkeypatch):
    elapsed = [0.0]
    monkeypatch.setattr(driver, 'time', SimpleNamespace(monotonic=lambda: elapsed[0]))
    def wall_clock():
        return 100.0

    db = tmp_path / 'state.db'
    bindings = [driver.HostedRoomBinding(room, 'gateway-a', 1)
                for room in ('room-stuck', 'room-healthy')]
    identities = [state.TaskIdentity(binding.room_id, task, 'thread', 'turn')
                  for binding, task in zip(bindings, ('task-stuck', 'task-healthy'))]
    for binding, identity in zip(bindings, identities):
        hosted_rooms.create_room(db, room_id=binding.room_id, name=binding.room_id,
            members=[{'profile': PROFILE, 'handle': PROFILE}], authority_gateway_id=binding.gateway_id)
        state.admit_task(db, identity, payload={'target_profile': PROFILE,
            'prompt': f'Run {binding.room_id}.', 'source_event_seq': 1}, clock=wall_clock)

    class FirstRoomStallsRPC(FakeSessionRPC):
        def submit(self, **kwargs):
            result = super().submit(**kwargs)
            if kwargs['task'].room_id == 'room-healthy':
                self.complete(kwargs['task'].task_id)
            else:
                # Advance only after the stalled turn was admitted with its deadline.
                elapsed[0] = 3.0
            return result

    runtime = driver.HostedRoomRuntime(db_path=db, rooms=bindings,
        rpc=FirstRoomStallsRPC(auto_complete=False), turn_lock=RecordingTurnLocks(),
        clock=wall_clock, lease_ttl_seconds=30, poll_interval_seconds=0.02,
        active_poll_interval_seconds=0.01, turn_timeout_seconds=2, max_concurrent_rooms=1)
    runtime.start()
    try:
        _wait_for(lambda: state.get_task(db, identities[0])['status'] == 'failed')
        _wait_for(lambda: state.get_task(db, identities[1])['status'] == 'settled')
    finally:
        assert runtime.stop(timeout=5.0)
    assert state.get_task(db, identities[0])['result']['reason_code'] == 'turn_deadline_exceeded'
    assert state.get_task(db, identities[1])['status'] == 'settled'
