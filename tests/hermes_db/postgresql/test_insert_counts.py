"""Real psycopg INSERT counts drive repair totals and worker change tracking."""

import json

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def test_route_repair_counts_only_new_rows_in_the_owning_store(pg_pair):
    first, other = pg_pair
    original = json.dumps({'session_id': 'original'})
    replacement = json.dumps({'session_id': 'replacement'})
    first_row = ('index', 'first', original, 1)
    second_row = ('index', 'second', original, 1)
    assert first.insert_gateway_routing_rows_if_absent([first_row, first_row, second_row]) == 2
    assert other.insert_gateway_routing_rows_if_absent([first_row]) == 1
    assert first.insert_gateway_routing_rows_if_absent([
        ('index', 'first', replacement, 2), ('index', 'third', original, 2)]) == 1
    assert first.insert_gateway_routing_rows_if_absent([first_row, second_row]) == 0
    resident = {row['session_key']: row['entry_json'] for row in first.list_gateway_routing_rows()}
    assert resident == {'first': original, 'second': original, 'third': original}
    assert len(other.list_gateway_routing_rows()) == 1


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
