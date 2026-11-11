"""Kanban swarm workflow; original connection, fence and off-connection effect boundaries are preserved."""
from hermes_db.domains.kanban import rules as _storage_shared_1
import json
import time
from sqlalchemy import select

from hermes_db.domains.kanban.postgres import catalog as create
from hermes_db.domains.kanban.postgres import repository as repo, runs as run_repo
from hermes_db.tables.kanban import tasks, comments
from hermes_db.core.values import decode_text, encode_text

def _blackboard(conn, store, root):

    rows = conn.execute(select(comments).where(repo.key(store, root, comments)).order_by(comments.c.created_at, comments.c.id)).mappings()
    return _storage_shared_1.merge_blackboard(store.result_values.comment(repo.decode_record(row)) for row in rows)



def _existing(conn, store, root):
    topology = _blackboard(conn, store, root).get('topology')
    if not isinstance(topology, dict):
        return None
    workers = [str(value) for value in topology.get('worker_ids', ()) if value]
    verifier, synthesizer = (topology.get('verifier_id'), topology.get('synthesizer_id'))
    return store.result_values.swarm_created(root, workers, str(verifier), str(synthesizer)) if workers and verifier and synthesizer else None
