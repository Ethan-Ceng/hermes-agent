"""Transfer and revoke local-file retention capabilities inside a shared schema."""

import json
from pathlib import Path
import re
import uuid

from hermes_db.errors import RetryableStorageError
from hermes_db.core.file_scope import owner_id
from hermes_db.domains.sessions.postgres.queries import file_grants as repo, media, sessions
from hermes_db.scope import DatabaseScope
from hermes_db.domains.sessions.postgres.support.search_projection import content_text
from hermes_state_media import PREFIX
from hermes_state_runtime import RuntimeStoreError


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


def _texts(snapshot):
    return [(content_text(row), row.get("api_content") or "") for row in snapshot["messages"]]


def _mentioned(reference, texts):
    tail = reference["sha256"] + "/" + Path(reference["path"]).name
    tails = (tail, tail.replace("/", "\\"))
    needles = [needle for part in tails for needle in (part, json.dumps(part)[1:-1])]
    return any(needle in text for pair in texts for text in pair for needle in needles)


def _known_media(conn, scope):
    references = {value["path"]: {"path": value["path"], "sha256": value["sha256"]}
        for _, value in media.candidates(conn, scope, PREFIX)}
    for path in media.held_media_paths(conn, scope):
        sha = Path(path).parent.name
        if re.fullmatch(r"[0-9a-f]{64}", sha):
            references[path] = {"path": path, "sha256": sha}
    return references.values()


def _subset(files, names, texts):
    return {"spillover": sorted(set(files["spillover"]) & names),
        "media": [reference for reference in files["media"] if _mentioned(reference, texts)]}


def _grant(conn, origin, target, files, *, file_owner_id=None):
    if origin.store_id == target.store_id or not (files["spillover"] or files["media"]):
        return
    grant_id, token = uuid.uuid4().hex, uuid.uuid4().hex
    value = {"version": 1, "grant_id": grant_id, "token": token, "origin_store_id": origin.require_store_id(),
        "origin_home": str(origin.profile_home), "file_owner_id": file_owner_id,
        "recipient_store_id": target.require_store_id(), "files": files}
    repo.put(conn, origin, repo.OWNED + grant_id, value)
    repo.put(conn, target, repo.RECEIVED + grant_id, value)


def transfer(conn, source, target, snapshot):
    from hermes_db.domains.sessions.postgres.support.archive_projection import spillover_names
    from hermes_db.integration.profile_context import OwnedProfileContext

    texts = _texts(snapshot)
    names = {name for row in snapshot["messages"] for name in (spillover_names(row) or ())}
    with OwnedProfileContext(source).activate():
        own = {"spillover": sorted(names), "media": [reference for reference in _known_media(conn, source) if _mentioned(reference, texts)]}
        local_owner = owner_id(source.profile_home, create=bool(own["spillover"] or own["media"]))
    _grant(conn, source, target, own, file_owner_id=local_owner)
    for _, proof in received(conn, source):
        origin = origin_scope(proof)
        value = repo.owned(conn, origin, proof, source)
        if value is None:
            raise RuntimeStoreError("file_reference_unknown")
        _grant(conn, origin, target, _subset(value["files"], names, texts), file_owner_id=value["file_owner_id"])


def _remaining(conn, scope, grants):
    from hermes_db.domains.sessions.postgres.queries.archive_refs import message_names
    from hermes_db.domains.sessions.postgres.support.retired_media import _history
    names = message_names(conn, scope)
    if names is None:
        return None
    references = [reference for _, value in grants for reference in value["files"]["media"]]
    mentioned = set()
    if references:
        mentioned, _ = _history(conn, scope, references)
        if mentioned is None:
            return None
        mentioned |= media.held_media_paths(conn, scope)
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
