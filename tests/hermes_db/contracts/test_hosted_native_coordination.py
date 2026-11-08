"""Independent room coordination cannot fall back to SQLite canonical sessions."""

from types import SimpleNamespace




def test_room_coordination_isolates_database_targets_and_schemas_but_not_credentials(tmp_path):
    from sqlalchemy.engine import make_url
    from gateway.session_hosted_storage import coordination_path
    from hermes_db.scope import DatabaseScope
    def store(dsn, schema='rooms'):
        return SimpleNamespace(scope=DatabaseScope(tmp_path, 'same-store'),
            _transactions=SimpleNamespace(engine=SimpleNamespace(url=make_url(dsn)), schema=schema))
    first = coordination_path(store('postgresql+psycopg://one:secret@host/first'))
    assert first == coordination_path(store('postgresql+psycopg://two:rotated@host/first'))
    assert first != coordination_path(store('postgresql+psycopg://one:secret@host/second'))
    assert first != coordination_path(store('postgresql+psycopg://one:secret@host/first', 'other'))
