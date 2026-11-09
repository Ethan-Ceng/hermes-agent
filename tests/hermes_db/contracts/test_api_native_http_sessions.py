"""HTTP session CRUD uses native owner resources and typed failure responses."""

from contextlib import contextmanager

import pytest


@pytest.mark.asyncio
async def test_native_http_creation_conflicts_retirement_and_unknown_commit(api_owner, native_registry, monkeypatch):
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer
    from gateway.config import PlatformConfig
    from gateway.platforms.api_server import APIServerAdapter
    from hermes_db.errors import StorageUnavailableError, UnknownCommitError
    from hermes_db.health import is_postgresql_store
    from hermes_db import factory
    registry, _opened = native_registry
    monkeypatch.setattr(factory, "acquire_db", lambda settings, scope: registry.acquire(settings.postgresql, scope))
    owner, db, _other = api_owner
    home = db.scope.profile_home
    (home / "config.yaml").write_text("storage:\n  backend: postgresql\n  postgresql:\n"
        f"    schema: hermes\n    store_id: {db.scope.store_id}\n")
    (home / ".env").write_text("HERMES_POSTGRES_DSN=postgresql://unused/db\n")
    adapter = APIServerAdapter(PlatformConfig(enabled=True))
    adapter.gateway_runner, adapter._session_db, adapter._api_key = owner.runner, db, "private-key"
    assert is_postgresql_store(adapter._response_store)
    app = web.Application()
    app.router.add_post("/api/sessions", adapter._handle_create_session)
    app.router.add_delete("/api/sessions/{session_id}", adapter._handle_delete_session)
    app.router.add_post("/v1/chat/completions", adapter._handle_chat_completions)
    headers = {"Authorization": "Bearer private-key"}
    try:
        async with TestClient(TestServer(app)) as client:
            result = await client.post("/api/sessions", json={"id": "created", "title": "unique"}, headers=headers)
            assert result.status == 201, await result.text()
            again = await client.post("/api/sessions", json={"id": "created"}, headers=headers)
            assert again.status == 409 and (await again.json())["error"]["code"] == "session_exists"
            conflict = await client.post("/api/sessions", json={"id": "bad-title", "title": "unique"}, headers=headers)
            assert conflict.status == 400 and db.get_session("bad-title") is None

            def history_unavailable(*args, **kwargs):
                raise StorageUnavailableError("history unavailable")

            with monkeypatch.context() as patch:
                patch.setattr(db, "get_messages_as_conversation", history_unavailable)
                history_error = await client.post("/v1/chat/completions", json={"model": "test-model",
                    "messages": [{"role": "user", "content": "must not run with empty history"}]},
                    headers={**headers, "X-Hermes-Session-Id": "created"})
                assert history_error.status == 503, await history_error.text()
                assert (await history_error.json())["error"]["code"] == "storage_unavailable"
            original = db._context.write

            @contextmanager
            def unavailable():
                raise StorageUnavailableError("redacted")
                yield  # pragma: no cover

            with monkeypatch.context() as patch:
                patch.setattr(db._context, 'write', unavailable)
                failed = await client.post("/api/sessions", json={"id": "unavailable"}, headers=headers)
                assert failed.status == 503 and (await failed.json())["error"]["code"] == "storage_unavailable"

            @contextmanager
            def confirmation_lost():
                with original() as conn:
                    yield conn
                raise UnknownCommitError("lost confirmation")

            with monkeypatch.context() as patch:
                patch.setattr(db._context, 'write', confirmation_lost)
                unknown = await client.post("/api/sessions", json={"id": "committed"}, headers=headers)
                assert unknown.status == 503 and (await unknown.json())["error"]["code"] == "storage_unknown_commit"
                assert unknown.headers["x-should-retry"] == "false"
            assert db.get_session("committed") is not None
            deleted = await client.delete("/api/sessions/created", headers=headers)
            assert deleted.status == 200, await deleted.text()
            retired = await client.post("/api/sessions", json={"id": "created"}, headers=headers)
            assert retired.status == 409 and (await retired.json())["error"]["code"] == "session_deleted"
            assert not (home / "state.db").exists()
    finally:
        adapter._response_store.close()
        adapter._run_idempotency_store.close()
