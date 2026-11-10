"""Collect retired local files after deletion commits, under the owning profile."""
import json
from sqlalchemy import select
from hermes_cli.db_scope import bind_profile_home
from hermes_db.tables.runtime import session_admissions
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
    from hermes_db.core.file_scope import owner_id
    from hermes_db.integration.media_grants import release_unused
    from hermes_cli.db_scope import OwnedProfileContext
    try:
        with context.profile.activate(), context.write() as conn:
            origins = release_unused(conn, context.scope)
        for scope, identity in origins:
            if identity is not None and owner_id(scope.profile_home) == identity:
                collect_scope(context.transactions, scope, OwnedProfileContext(scope))
    except (StorageError, ValueError, TypeError, KeyError):
        return

def _history(conn, scope, references):
    from tools.tool_result_storage import spillover_names_in_text
    needles, mentioned, spill_names = ({}, set(), set())
    for reference in references:
        for sep in ('/', '\\'):
            tail = reference['sha256'] + sep + Path(reference['path']).name
            needles[tail] = needles[json.dumps(tail)[1:-1]] = reference['path']
    matched = 0
    for content, api in media.text_rows(conn, scope):
        text = content.decode('utf-8', 'replace') if isinstance(content, bytes) else str(content)
        spill_names |= spillover_names_in_text(text, api)
        mentioned.update((raw for needle, raw in needles.items() if needle in text or needle in (api or '')))
        matched += int('spillover' in text or bool(needles))
        if matched > 20000:
            return (None, None)
    return (mentioned, spill_names)

def _collect_spills(scope, candidates, referenced):
    from hermes_db.core.file_scope import identity, owner_id
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
    rows = conn.execute(select(session_admissions.c.status, session_admissions.c.request_id, session_admissions.c.payload_json)
        .where(session_admissions.c.store_id == scope.require_store_id()).execution_options(yield_per=512))
    with bind_profile_home(scope):
        for status, request_id, raw in rows:
            payload = json.loads(raw)
            refs = list(payload.get("api_turn_v1", {}).get("media", []))
            if status != "terminal":
                refs.extend(admission_media_references(payload))
                refs.extend(hosted_document_references(request_id, payload))
            held.update(reference["path"] for reference in refs)
    return held
