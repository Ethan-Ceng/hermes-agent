"""Existing session lifecycle hook consumer, invoked only after commit."""

import logging


def emit_deleted(profile, session_ids, *, reason, primary=None):
    from hermes_constants import profile_name_for_home
    from hermes_cli.lifecycle import invoke_hook

    ids = sorted(set(session_ids))
    if not ids:
        return
    payload = {"session_id": primary if primary in ids else ids[0], "reason": reason,
               "profile": profile_name_for_home(profile.scope.profile_home)}
    if len(ids) > 1:
        payload["deleted_ids"] = ids
    try:
        with profile.activate():
            invoke_hook("on_session_delete", **payload)
    except Exception:
        logging.getLogger(__name__).exception("Session lifecycle hook failed after committed storage change")
