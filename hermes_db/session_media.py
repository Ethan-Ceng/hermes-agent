"""Collect retired local files after deletion commits, under the owning profile."""

import json
from pathlib import Path

from hermes_db.repositories import media, sessions
from hermes_state_media import PREFIX, SPILLOVER_PREFIX


def collect(store):
    with store._profile.activate(), store._write() as conn:
        # Local unlink is short; the mapping fence prevents an accepted input or
        # branch from publishing a new reference between the check and unlink.
        # Candidates were committed by the earlier deletion transaction, so a
        # failed cleanup keeps them available for the next pass.
        sessions.lock_store(conn, store.scope, exclusive=True)
        refs, spills = media.candidates(conn, store.scope, PREFIX), media.candidates(conn, store.scope, SPILLOVER_PREFIX)
        if not refs and not spills:
            return
        mentions, names = _history(conn, store.scope, [value for _, value in refs])
        if mentions is None:
            return
        done = _collect_spills(store.scope.profile_home / "cache" / "spillover", spills, names)
        done.extend(_collect_media(conn, store.scope, refs, mentions))
        media.forget(conn, store.scope, done)


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
        mentioned.update(raw for needle, raw in needles.items() if needle in text)
        matched += int("spillover" in text or bool(needles))
        if matched > 20000:
            return None, None
    return mentioned, spill_names


def _collect_spills(root, candidates, referenced):
    done, root = [], root.resolve()
    for key, name in candidates:
        # Names come from the existing pointer parser; still require an exact
        # basename so a corrupt control row cannot unlink outside its cache.
        if not isinstance(name, str) or Path(name).name != name or name in (".", ".."):
            continue
        path = root / name
        if name in referenced or not path.resolve().is_relative_to(root):
            continue
        try:
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
