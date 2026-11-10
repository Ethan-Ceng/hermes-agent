"""Read and release existing local-file retention grants inside a shared schema."""

from pathlib import Path

from hermes_db.integration.media_retirement import held_media_paths
from hermes_db.errors import RetryableStorageError
from hermes_db.domains.sessions.postgres.queries import file_grants as repo, sessions
from hermes_db.scope import DatabaseScope


def received(conn, scope):
    return repo.rows(conn, scope, repo.RECEIVED)


def origin_scope(proof):
    return DatabaseScope(Path(proof["origin_home"]), proof["origin_store_id"])


def lock_scopes(conn, scopes, *, receivers=()):
    planned = {scope.require_store_id(): scope for scope in scopes}
    for receiver in receivers:
        for _, proof in received(conn, receiver):
            origin = origin_scope(proof)
            planned.setdefault(origin.require_store_id(), origin)
    for key in sorted(planned):
        sessions.lock_store(conn, planned[key], exclusive=True)
    for receiver in receivers:
        if any(proof["origin_store_id"] not in planned for _, proof in received(conn, receiver)):
            raise RetryableStorageError("File reference scopes changed; retry after inspecting the move receipt")
    return planned


def _remaining(conn, scope, grants):
    from hermes_db.domains.sessions.postgres.queries.archive_refs import message_names
    from hermes_db.integration.media_retirement import _history
    names = message_names(conn, scope)
    if names is None:
        return None
    references = [reference for _, value in grants for reference in value["files"]["media"]]
    mentioned = set()
    if references:
        mentioned, _ = _history(conn, scope, references)
        if mentioned is None:
            return None
        mentioned |= held_media_paths(conn, scope)
    return names, mentioned


def release_unused(conn, scope):
    lock_scopes(conn, [scope], receivers=[scope])
    grants = received(conn, scope)
    remaining = _remaining(conn, scope, grants)
    if remaining is None:
        return []
    names, paths = remaining
    origins = {}
    for key, proof in grants:
        origin = origin_scope(proof)
        value = repo.owned(conn, origin, proof, scope)
        if value is None:
            continue
        files = {"spillover": sorted(set(value["files"]["spillover"]) & names),
            "media": [reference for reference in value["files"]["media"] if reference["path"] in paths]}
        if files == value["files"]:
            continue
        if files["spillover"] or files["media"]:
            value = {**value, "files": files}
            repo.put(conn, origin, repo.OWNED + proof["grant_id"], value)
            repo.put(conn, scope, key, value)
        else:
            repo.drop(conn, origin, repo.OWNED + proof["grant_id"])
            repo.drop(conn, scope, key)
        origins[(origin.store_id, str(origin.profile_home), value["file_owner_id"])] = (origin, value["file_owner_id"])
    return list(origins.values())
