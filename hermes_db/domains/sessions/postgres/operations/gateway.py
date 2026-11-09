"""Whole routing writes share the map fence with publication and retirement."""

import time

from hermes_db.domains.sessions.postgres.queries import gateway as repo, sessions
from hermes_db.tables.gateway import gateway_routing


def save_route(conn, scope, key, entry, *, namespace=""):
    sessions.lock_store(conn, scope, exclusive=True)
    return repo.save_route(conn, scope, namespace, key, entry, time.time())


def replace_routes(conn, scope, entries, *, namespace=""):
    sessions.lock_store(conn, scope, exclusive=True)
    conn.execute(gateway_routing.delete().where(*repo.where(scope, namespace)))
    rejected, now = set(), time.time()
    for key, entry in entries.items():
        if key and entry and not repo.save_route(conn, scope, namespace, key, entry, now):
            rejected.add(key)
    return rejected


def retire_routes(conn, scope, session_ids, *, namespace, expiring=()):
    sessions.lock_store(conn, scope, exclusive=True)
    repo.retire_shared(conn, scope, namespace, session_ids, expiring=expiring, now=time.time())
