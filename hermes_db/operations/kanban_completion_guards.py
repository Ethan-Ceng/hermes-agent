"""Completion evidence is scoped, audited and never replaced with a silent no-op."""

from sqlalchemy import select

from hermes_db.repositories import kanban as repo
from hermes_db.tables.kanban import tasks
from hermes_db.values import decode_text, encode_text


def verify_on_connection(conn, store, task_id, claimed_ids):
    ordered = list(dict.fromkeys(str(value).strip() for value in claimed_ids if str(value).strip()))
    task = repo.get(conn, store, task_id)
    if task is None:
        return [], ordered
    found = {decode_text(tid): decode_text(creator) for tid, creator in conn.execute(select(tasks.c.id, tasks.c.created_by)
        .where(repo.scope(tasks, store), tasks.c.id.in_([encode_text(value) for value in ordered])))}
    children = set(repo.linked_ids(conn, store, task_id, parents=False))
    verified, phantom = [], []
    for tid in ordered:
        creator = found.get(tid)
        trusted = creator is not None and ((task["assignee"] and creator == task["assignee"]) or creator == task_id or tid in children)
        (verified if trusted else phantom).append(tid)
    return verified, phantom


def _verify_created_cards(store, completing_task_id, claimed_ids):
    with store.read() as conn:
        return verify_on_connection(conn, store, completing_task_id, claimed_ids or ())


def _audit(store, task_id, kind, payload):
    with store.write() as conn:
        if repo.get(conn, store, task_id) is not None:
            repo.event(conn, store, task_id, kind, payload)


def _gate_created_cards(store, task_id, created_cards, preview_text):
    from hermes_cli import kanban_db as kb
    if not created_cards:
        return []
    verified, phantom = _verify_created_cards(store, task_id, created_cards)
    if phantom:
        _audit(store, task_id, "completion_blocked_hallucination", {"phantom_cards": phantom,
            "verified_cards": verified, "summary_preview": kb._first_line(preview_text, 200) or None})
        raise kb.HallucinatedCardsError(phantom, task_id)
    return verified


def _gate_empty_completion(store, task_id, *, result, summary):
    from hermes_cli import kanban_db as kb
    with store.read() as conn:
        row = repo.get(conn, store, task_id)
    if row is None or row["status"] == "review":
        return
    if any(kb._substantive_text(value) for value in (result, summary, row["result"])):
        return
    _audit(store, task_id, "completion_blocked_empty_result", {"result_preview": kb._first_line(result, 200) or None,
        "summary_preview": kb._first_line(summary, 200) or None})
    raise kb.EmptyCompletionError(task_id)


def _scan_prose_for_phantom_ids(store, text):
    from hermes_cli.kanban_db import _TASK_ID_PROSE_RE
    ids = list(dict.fromkeys(_TASK_ID_PROSE_RE.findall(text or "")))
    with store.read() as conn:
        found = {decode_text(tid) for tid in conn.scalars(select(tasks.c.id).where(repo.scope(tasks, store),
                 tasks.c.id.in_([encode_text(value) for value in ids])))}
    return [tid for tid in ids if tid not in found]
