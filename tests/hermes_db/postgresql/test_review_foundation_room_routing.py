"""Independent review repro for Cron's explicit cross-Profile room selector."""

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def test_explicit_cron_target_writes_only_target_profile(pg_profiles, monkeypatch):
    from cron.scheduler_delivery_room import deliver_to_room
    from gateway import hosted_rooms as rooms
    from hermes_cli import profiles
    from hermes_cli.db_setup import _owning_profile
    from hermes_db.factory import acquire_profile_domain
    from hermes_db.domains.runtime.postgres.queries.runtime import set_meta
    monkeypatch.setattr(rooms, 'local_authority_gateway_id', lambda: 'review-gateway')
    references = []
    homes = []
    for profile in ('one', 'two'):
        with pg_profiles(profile) as home:
            reference = rooms.default_db_path()
            rooms.create_room(reference, room_id='same-room', name=profile, members=[],
                              authority_gateway_id='review-gateway')
            with acquire_profile_domain('sessions') as resource, resource.write() as connection:
                set_meta(connection, resource.scope, 'gateway.hosted.owner.v1:same-room', 'owner')
            references.append(reference)
            homes.append(home)
    monkeypatch.setattr(profiles, 'profile_exists', lambda name: name == 'two')
    monkeypatch.setattr(profiles, 'get_profile_dir', lambda name: homes[1])
    with _owning_profile(homes[0]):
        assert deliver_to_room({'id': 'job', 'execution_id': 'attempt'}, 'for target only', 'same-room@two') is None
    source = rooms.read_events(references[0], room_id='same-room')['events']
    target = rooms.read_events(references[1], room_id='same-room')['events']
    assert len(source) == 0 and len(target) == 1, {'source_events': source, 'target_events': target}
