"""Rejected fan-out must preserve children held for manual review."""

from pathlib import Path

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def test_rejected_decomposition_preserves_manual_review_state_and_events(pg_profiles, tmp_path, monkeypatch):
    import hermes_constants
    from hermes_cli import kanban_db as kb
    from hermes_cli import kanban_db_connect as kbc
    from hermes_cli.kanban_db_graph import decompose_triage_task

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(hermes_constants, "_default_hermes_root_memo", None)
    monkeypatch.setenv("HERMES_KANBAN_HOME", str(tmp_path / "shared-kanban"))
    monkeypatch.setenv("HERMES_KANBAN_DB", str(tmp_path / "path-override" / "kanban.db"))
    monkeypatch.delenv("HERMES_KANBAN_BOARD", raising=False)
    monkeypatch.delenv("HERMES_KANBAN_TASK", raising=False)
    with pg_profiles("one"), kbc.connect_closing() as store:
        root = kb.create_task(store, title="manual review root", triage=True)
        children = [{"title": "await human review", "assignee": "coder"}]
        ids = decompose_triage_task(store, root, root_assignee="orchestrator",
                                   children=children, auto_promote=False)
        child = ids[0]
        before = [event.kind for event in kb.list_events(store, child)]
        assert kb.get_task(store, child).status == "todo"

        assert decompose_triage_task(store, root, root_assignee=None, children=children) is None
        assert (kb.get_task(store, child).status,
                [event.kind for event in kb.list_events(store, child)]) == ("todo", before)

        kb.recompute_ready(store)
        assert kb.get_task(store, child).status == "ready"
        assert [event.kind for event in kb.list_events(store, child)] == [*before, "promoted"]
