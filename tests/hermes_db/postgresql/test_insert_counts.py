"""Real psycopg INSERT counts preserve worker change tracking."""

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]




def test_worker_change_tracker_distinguishes_noop_insert_from_new_row(pg_store):
    from sqlalchemy.dialects.postgresql import insert
    from hermes_db.backends.postgresql.changes import track_changes
    from hermes_db.tables.runtime import state_meta
    statement = insert(state_meta).values(store_id=pg_store.scope.store_id, key='observed', value='same')
    statement = statement.on_conflict_do_nothing(index_elements=list(state_meta.primary_key.columns))
    with pg_store._write() as conn:
        conn.execute(statement)
        with track_changes(conn) as noop:
            conn.execute(statement)
        assert not noop['changed']
        with track_changes(conn) as changed:
            conn.execute(statement.values(key='new'))
        assert changed['changed']
