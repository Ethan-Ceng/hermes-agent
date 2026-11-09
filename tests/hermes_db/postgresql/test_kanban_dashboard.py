"""Bundled dashboard discovery, HTTP reads and threaded event tails on real PG."""

import sys
import asyncio
from pathlib import Path
import httpx
import pytest
from fastapi import FastAPI

from hermes_cli import kanban_db as kb, kanban_db_connect as kbc

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def dashboard():
    from hermes_cli.web_server_dashboard import _discover_dashboard_plugins, _mount_one_plugin_api, _plugin_api_mount_lock
    root = Path(__file__).resolve().parents[3]
    plugin = next(item for item in _discover_dashboard_plugins([(root / "plugins", "bundled")]) if item["name"] == "kanban")
    app = FastAPI()
    with _plugin_api_mount_lock:
        assert _mount_one_plugin_api(app, plugin, {"kanban"}, set())
    return app, sys.modules["hermes_dashboard_plugin_kanban"]


@pytest.mark.asyncio
async def test_dashboard_reads_real_scoped_tasks_rollups_and_worker_rows(pg_profiles):
    with pg_profiles("one"), kbc.connect_closing() as store:
        parent = kb.create_task(store, title="dashboard🙂", tenant="team")
        child = kb.create_task(store, title="dependent", parents=[parent])
        kb.add_comment(store, parent, "user", "visible")
        app, _module = dashboard()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/plugins/kanban/board")
            assert response.status_code == 200, response.text
            cards = [task for column in response.json()["columns"] for task in column["tasks"]]
            card = next(task for task in cards if task["id"] == parent)
            assert card["title"] == "dashboard🙂" and card["comment_count"] == 1
            assert card["link_counts"]["children"] == 1
            assert card["progress"] == {"done": 0, "total": 1}
            detail = await client.get(f"/api/plugins/kanban/tasks/{child}")
            assert detail.status_code == 200 and detail.json()["links"]["parents"] == [parent]
            assert (await client.get("/api/plugins/kanban/workers/active")).json()["workers"] == []
            boards = (await client.get("/api/plugins/kanban/boards")).json()["boards"]
            assert next(item for item in boards if item["slug"] == "default")["counts"]["ready"] == 1


@pytest.mark.asyncio
async def test_event_tailer_keeps_owner_scope_across_thread_and_profile_switch(pg_profiles):
    with pg_profiles("one"), kbc.connect_closing() as store:
        task = kb.create_task(store, title="tail")
        _app, module = dashboard()
        tail = module._EventTail(None)
        try:
            cursor = await tail.latest()
            kb.add_comment(store, task, "worker", "event🙂\x00")
            with pg_profiles("two"):
                next_cursor, events = await tail.poll(cursor)
            assert next_cursor > cursor
            assert [event["kind"] for event in events] == ["commented"]
            assert events[0]["task_id"] == task
        finally:
            await tail.shutdown()


@pytest.mark.asyncio
async def test_dashboard_reopen_invalidates_live_descendants_atomically_and_archive_closes_run(pg_profiles):
    with pg_profiles("one"), kbc.connect_closing() as store:
        parent = kb.create_task(store, title="parent")
        assert kb.complete_task(store, parent, summary="upstream delivered")
        child = kb.create_task(store, title="child", parents=[parent])
        claim = kb.claim_task(store, child)
        app, _module = dashboard()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.patch(f"/api/plugins/kanban/tasks/{parent}", json={"title": "reopened🙂", "status": "ready"})
            assert response.status_code == 200, response.text
            assert kb.get_task(store, parent).title == "reopened🙂"
            assert kb.get_task(store, child).status == "todo"
            assert kb.get_run(store, claim.current_run_id).outcome == "reclaimed"
            assert any(event.kind == "descendant_invalidated" for event in kb.list_events(store, child))
            refused = await client.patch(f"/api/plugins/kanban/tasks/{child}", json={"status": "ready"})
            assert refused.status_code == 409 and parent in refused.text
            archived = await client.patch(f"/api/plugins/kanban/tasks/{child}", json={"status": "archived"})
            assert archived.status_code == 200 and kb.get_task(store, child).status == "archived"


def test_parent_and_descendant_reopen_roll_back_together_on_event_failure(pg_profiles, monkeypatch):
    from hermes_db.domains.kanban.postgres.operations.dashboard import _set_status_direct
    from hermes_db.domains.kanban.postgres.queries import kanban as repo
    with pg_profiles("one"), kbc.connect_closing() as store:
        parent = kb.create_task(store, title="completed")
        assert kb.complete_task(store, parent, summary="delivered")
        child = kb.create_task(store, title="running child", parents=[parent])
        claim = kb.claim_task(store, child)
        original = repo.event

        def fail_event(conn, store, task_id, kind, *args, **kwargs):
            if kind == "descendant_invalidated":
                raise RuntimeError("test audit failed")
            return original(conn, store, task_id, kind, *args, **kwargs)

        monkeypatch.setattr(repo, "event", fail_event)
        with pytest.raises(RuntimeError, match="audit failed"):
            _set_status_direct(store, parent, "ready")
        assert kb.get_task(store, parent).status == "done"
        assert kb.get_task(store, child).status == "running"
        assert kb.get_run(store, claim.current_run_id).ended_at is None


@pytest.mark.asyncio
async def test_parallel_http_imports_keep_profile_scope_and_distinct_board_generations(pg_profiles, tmp_path):
    from tests.hermes_db.postgresql.test_kanban_transfer import make_archive
    archive, parent, child, _run = make_archive(pg_profiles, tmp_path)
    with pg_profiles("two"):
        app, _module = dashboard()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            responses = await asyncio.gather(*(client.post("/api/plugins/kanban/boards/import",
                json={"archive": archive, "slug": "parallel"}) for _index in range(2)))
        assert [response.status_code for response in responses] == [200, 200], [response.text for response in responses]
        slugs = sorted(response.json()["board"] for response in responses)
        assert slugs == ["parallel", "parallel-2"]
        roots = []
        for slug in slugs:
            with kbc.connect_closing(board=slug) as store:
                assert kb.parent_ids(store, child) == [parent]
                attachment, = kb.list_attachments(store, parent)
                assert Path(attachment.stored_path).read_bytes() == b"retained\x00bytes"
                roots.append(store.board_id)
        assert roots[0] != roots[1]
