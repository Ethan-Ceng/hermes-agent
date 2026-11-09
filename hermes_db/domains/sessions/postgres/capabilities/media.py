"""Collect retired local files after deletion commits, under the owning profile."""

import json
from pathlib import Path

from hermes_db.domains.sessions.postgres.queries import media, sessions
from hermes_state_media import PREFIX, SPILLOVER_PREFIX


def collect(store):
    _release_foreign(store)
    collect_scope(store._transactions, store.scope, store._profile)


def release(store, references, *, retain_history):
    from hermes_db.domains.sessions.postgres.queries import file_grants
    with store._profile.activate(), store._write() as conn:
        sessions.lock_store(conn, store.scope, exclusive=True)
        mentions, _ = _history(conn, store.scope, references) if retain_history else (set(), set())
        if mentions is None:
            return 0
        _, pins = file_grants.pins(conn, store.scope)
        mentions.update(reference["path"] for reference in pins)
        candidates = [(str(index), reference) for index, reference in enumerate(references)]
        return len(_collect_media(conn, store.scope, candidates, mentions))


def collect_scope(transactions, scope, profile):
    from hermes_db.domains.sessions.postgres.queries import archive_refs, file_grants
    with profile.activate(), transactions.write() as conn:
        # Local unlink is short; the mapping fence prevents an accepted input or
        # branch from publishing a new reference between the check and unlink.
        # Candidates were committed by the earlier deletion transaction, so a
        # failed cleanup keeps them available for the next pass.
        sessions.lock_store(conn, scope, exclusive=True)
        refs, spills = media.candidates(conn, scope, PREFIX), media.candidates(conn, scope, SPILLOVER_PREFIX)
        if not refs and not spills:
            return
        mentions, _ = _history(conn, scope, [value for _, value in refs])
        names = archive_refs.referenced_names(conn, scope)
        if mentions is None or names is None:
            return
        _, pinned = file_grants.pins(conn, scope)
        mentions.update(reference["path"] for reference in pinned)
        done = _collect_spills(scope, spills, names)
        done.extend(_collect_media(conn, scope, refs, mentions))
        media.forget(conn, scope, done)


def _release_foreign(store):
    from hermes_db.errors import StorageError
    from hermes_db.core.file_scope import owner_id
    from hermes_db.integration.postgres.operations.file_grants import release_unused
    from hermes_db.integration.profile_context import OwnedProfileContext
    try:
        with store._profile.activate(), store._write() as conn:
            origins = release_unused(conn, store.scope)
        for scope, identity in origins:
            if identity is not None and owner_id(scope.profile_home) == identity:
                collect_scope(store._transactions, scope, OwnedProfileContext(scope))
    except (StorageError, ValueError, TypeError, KeyError):
        # Grants and retirement candidates are durable; a later owned sweep
        # retries without guessing that unreachable references have vanished.
        return


def _history(conn, scope, references):
    from tools.tool_result_storage import spillover_names_in_text

    needles, mentioned, spill_names = {}, set(), set()
    for reference in references:
        for sep in ("/", "\\"):
            tail = reference["sha256"] + sep + Path(reference["path"]).name
            needles[tail] = needles[json.dumps(tail)[1:-1]] = reference["path"]
    matched = 0
    for content, api in media.text_rows(conn, scope):
        text = content.decode("utf-8", "replace") if isinstance(content, bytes) else str(content)
        spill_names |= spillover_names_in_text(text, api)
        mentioned.update(raw for needle, raw in needles.items() if needle in text or needle in (api or ""))
        matched += int("spillover" in text or bool(needles))
        if matched > 20000:
            return None, None
    return mentioned, spill_names


def _collect_spills(scope, candidates, referenced):
    from hermes_db.core.file_scope import identity, owner_id
    done, root = [], (scope.profile_home / "cache" / "spillover").resolve()
    owner = owner_id(scope.profile_home)
    for key, reference in candidates:
        name = reference["name"]
        # Names come from the existing pointer parser; still require an exact
        # basename so a corrupt control row cannot unlink outside its cache.
        if not isinstance(name, str) or Path(name).name != name or name in (".", ".."):
            continue
        path = root / name
        if name in referenced or not path.resolve().is_relative_to(root):
            continue
        try:
            if not path.exists():
                done.append(key)
                continue
            if owner is None or reference["owner"] != owner:
                continue
            if identity(path) != reference["identity"]:
                # The retired generation is already gone; never unlink its replacement.
                done.append(key)
                continue
            path.unlink(missing_ok=True)
        except OSError:
            continue
        done.append(key)
    return done


def _collect_media(conn, scope, candidates, mentions):
    from gateway.session_ingress_media import _file_identity, _held_file_identities, _lease_lock, _leases, native_inputs_root

    root = native_inputs_root()
    held = media.held_media_paths(conn, scope)
    identities = _held_file_identities(held, root)
    if identities is None:
        return []
    done = []
    for key, reference in candidates:
        path = Path(reference["path"])
        if path.parent.parent != root or path.parent.name != reference["sha256"] or str(path) in held | mentions:
            continue
        try:
            with _lease_lock:
                if str(path) in _leases or path.parent.resolve() != path.parent:
                    continue
                if path.exists() and _file_identity(path) in identities:
                    continue
                path.unlink(missing_ok=True)
            done.append(key)
            if path.parent.exists() and not any(path.parent.iterdir()):
                path.parent.rmdir()
        except (OSError, ValueError):
            continue
    return done
