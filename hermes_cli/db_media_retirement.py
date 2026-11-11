"""Collect retired local files after deletion commits, under the owning profile."""
import json
from hermes_cli.db_scope import bind_profile_home
from pathlib import Path
from hermes_db.domains.sessions.postgres.queries import media, sessions
from hermes_db.domains.runtime.receipts import RETIRED_MEDIA_PREFIX as PREFIX, MEDIA_SPILLOVER_PREFIX as SPILLOVER_PREFIX

def collect(context):
    _release_foreign(context)
    collect_scope(context.transactions, context.scope, context.profile)

def release(context, references, *, retain_history):
    from hermes_db.domains.sessions.postgres.queries import file_grants
    with context.profile.activate(), context.write() as conn:
        sessions.lock_store(conn, context.scope, exclusive=True)
        mentions, _ = _history(conn, context.scope, references) if retain_history else (set(), set())
        if mentions is None:
            return 0
        _, pins = file_grants.pins(conn, context.scope)
        mentions.update(reference['path'] for reference in pins)
        candidates = [(str(index), reference) for index, reference in enumerate(references)]
        return len(_collect_media(conn, context.scope, candidates, mentions))

def collect_scope(transactions, scope, profile):
    from hermes_db.domains.sessions.postgres.queries import archive_refs, file_grants
    with profile.activate(), transactions.write() as conn:
        sessions.lock_store(conn, scope, exclusive=True)
        refs, spills = (media.candidates(conn, scope, PREFIX), media.candidates(conn, scope, SPILLOVER_PREFIX))
        if not refs and (not spills):
            return
        mentions, _ = _history(conn, scope, [value for _, value in refs])
        names = archive_refs.referenced_names(conn, scope)
        if mentions is None or names is None:
            return
        _, pinned = file_grants.pins(conn, scope)
        mentions.update(reference['path'] for reference in pinned)
        done = _collect_spills(scope, spills, names)
        done.extend(_collect_media(conn, scope, refs, mentions))
        media.forget(conn, scope, done)

def _release_foreign(context):
    from hermes_db.errors import StorageError
    from hermes_cli.db_file_identity import owner_id
    from hermes_db.domains.sessions.postgres.media_grants import release_unused
    from hermes_cli.db_scope import OwnedProfileContext
    try:
        with context.profile.activate(), context.write() as conn:
            origins = release_unused(conn, context.scope, history=_history, held_media_paths=held_media_paths)
        for scope, identity in origins:
            if identity is not None and owner_id(scope.profile_home) == identity:
                collect_scope(context.transactions, scope, OwnedProfileContext(scope))
    except (StorageError, ValueError, TypeError, KeyError):
        return


def _collect_spills(scope, candidates, referenced):
    from hermes_cli.db_file_identity import identity, owner_id
    done, root = ([], (scope.profile_home / 'cache' / 'spillover').resolve())
    owner = owner_id(scope.profile_home)
    for key, reference in candidates:
        name = reference['name']
        if not isinstance(name, str) or Path(name).name != name or name in ('.', '..'):
            continue
        path = root / name
        if name in referenced or not path.resolve().is_relative_to(root):
            continue
        try:
            if not path.exists():
                done.append(key)
                continue
            if owner is None or reference['owner'] != owner:
                continue
            if identity(path) != reference['identity']:
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
    held = held_media_paths(conn, scope)
    identities = _held_file_identities(held, root)
    if identities is None:
        return []
    done = []
    for key, reference in candidates:
        path = Path(reference['path'])
        if path.parent.parent != root or path.parent.name != reference['sha256'] or str(path) in held | mentions:
            continue
        try:
            with _lease_lock:
                if str(path) in _leases or path.parent.resolve() != path.parent:
                    continue
                if path.exists() and _file_identity(path) in identities:
                    continue
                path.unlink(missing_ok=True)
            done.append(key)
            if path.parent.exists() and (not any(path.parent.iterdir())):
                path.parent.rmdir()
        except (OSError, ValueError):
            continue
    return done

def held_media_paths(conn, scope):
    from gateway.session_contract import admission_media_references
    from gateway.session_ingress_media import hosted_document_references
    held = set()
    from hermes_db.domains.sessions.postgres.queries.media_retirement import held_payloads
    rows = held_payloads(conn, scope)
    with bind_profile_home(scope):
        for status, request_id, raw in rows:
            payload = json.loads(raw)
            refs = list(payload.get("api_turn_v1", {}).get("media", []))
            if status != "terminal":
                refs.extend(admission_media_references(payload))
                refs.extend(hosted_document_references(request_id, payload))
            held.update(reference["path"] for reference in refs)
    return held


def _history(conn, scope, references):
    from hermes_db.domains.sessions.postgres.queries.media_retirement import history
    from tools.tool_result_storage import spillover_names_in_text
    return history(conn, scope, references, spillover_names=spillover_names_in_text)


def retire_spillover(conn, scope, session_ids):
    from hermes_db.domains.sessions.postgres.queries.media import _candidate, text_rows
    from hermes_cli.db_file_identity import identity, owner_id
    from tools.tool_result_storage import spillover_names_in_text
    root = scope.profile_home / "cache" / "spillover"
    owner = owner_id(scope.profile_home, create=True)
    for start in range(0, len(session_ids), 1000):
        for content, api in text_rows(conn, scope, session_ids[start:start + 1000]):
            for name in spillover_names_in_text(content, api):
                try:
                    stamp = identity(root / name)
                except OSError:
                    stamp = None
                _candidate(conn, scope, SPILLOVER_PREFIX + name,
                    {"name": name, "owner": owner, "identity": stamp})
