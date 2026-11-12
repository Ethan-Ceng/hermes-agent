"""25 MiB attachments retain the bounded worker outbox and Board commit receipts."""

from contextlib import closing
import asyncio
import base64
import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pytest

from agent.runtime_session_store import RuntimeSessionStore
from gateway.session_worker_kanban import worker_kanban
from hermes_cli import kanban_db as kb, kanban_db_connect as kbc
from hermes_cli.db_sessions import open_session_store
from hermes_cli.kanban_storage_wire import unpack
from agent.runtime_kanban_storage import WorkerBoardResource
from tests.hermes_db.postgresql.test_kanban_interactive_worker import setup_owner, call

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def test_maximum_attachment_uses_small_frames_and_replays_lost_commit(pg_profiles, monkeypatch):
    from hermes_db.errors import UnknownCommitError
    from hermes_db.infra.postgresql.transactions import Transactions
    with pg_profiles("one") as home, closing(open_session_store(home / "state.db")) as db:
        _runtime, connection, scope = setup_owner(home, db, monkeypatch)
        context = asyncio.run(call(connection, scope, "board.resolve"))
        frames = []
        def rpc(method, **params):
            frames.append(len(json.dumps(params)))
            return asyncio.run(worker_kanban(connection, None, params, command=method.endswith("command")))
        with closing(RuntimeSessionStore(rpc, scope, home / "upload-outbox")) as worker:
            proxy = WorkerBoardResource(worker, context)
            task = kb.create_task(proxy, title="large attachment", workspace_kind="scratch")
            data = b"\x00\xff" * (kb.KANBAN_ATTACHMENT_MAX_BYTES // 2)
            assert len(data) == kb.KANBAN_ATTACHMENT_MAX_BYTES
            original_write = Transactions.write
            armed = [True]
            from contextlib import contextmanager
            @contextmanager
            def lose_ack(self, *args, **kwargs):
                with original_write(self, *args, **kwargs) as conn:
                    yield conn
                if armed[0]:
                    armed[0] = False
                    raise UnknownCommitError("injected upload commit confirmation loss")
            with monkeypatch.context() as patch:
                patch.setattr(Transactions, "write", lose_ack)
                with pytest.raises(UnknownCommitError):
                    kb.store_attachment_bytes(proxy, task, "maximum.bin", data)
            assert worker.journal["kanban_pending"] is not None
            assert worker.path.stat().st_size < 65536
            result, = worker.retry_pending()
            attachment_id = unpack(result)
            attachment = kb.get_attachment(proxy, attachment_id)
            assert attachment.size == len(data)
            assert hashlib.sha256(Path(attachment.stored_path).read_bytes()).digest() == hashlib.sha256(data).digest()
            assert len(kb.list_attachments(proxy, task)) == 1
            assert max(frames) < 1024 * 1024
            with pytest.raises(kb.AttachmentTooLarge):
                kb.store_attachment_bytes(proxy, task, "too-large.bin", data + b"x")
            assert len(kb.list_attachments(proxy, task)) == 1
    with pg_profiles("one"), kbc.connect_closing() as reopened:
        attachment, = kb.list_attachments(reopened, task)
        assert Path(attachment.stored_path).stat().st_size == kb.KANBAN_ATTACHMENT_MAX_BYTES
        from hermes_cli.db_maintenance import maintain_profile
        maintain_profile(home)
        assert not list((home / "kanban" / "uploads").rglob("*.part"))
        assert list((home / "kanban" / "uploads").rglob(".reclaimed"))
        assert Path(attachment.stored_path).stat().st_size == kb.KANBAN_ATTACHMENT_MAX_BYTES


def test_upload_chunks_reject_replacement_bad_shape_and_cross_board_scope(pg_profiles, monkeypatch):
    from hermes_state_runtime import RuntimeStoreError
    with pg_profiles("one") as home, closing(open_session_store(home / "state.db")) as db:
        _runtime, connection, scope = setup_owner(home, db, monkeypatch)
        context = asyncio.run(call(connection, scope, "board.resolve"))
        target = {"board": "default", "board_id": context["owner"]["board_id"]}
        payload = dict(target=target, upload_id=uuid4().hex, size=3,
                       sha256=hashlib.sha256(b"abc").hexdigest(), index=0, data=base64.b64encode(b"abc").decode())
        def send(value):
            return unpack(asyncio.run(worker_kanban(connection, None, dict(scope, operation="attachment.chunk",
                payload=value, command_id=uuid4().hex), command=True)))
        assert send(payload) == send(payload) == {"index": 0, "size": 3}
        for changed, reason in ((payload | {"data": base64.b64encode(b"xyz").decode()}, "admission_conflict"),
                (payload | {"index": -1}, "invalid_params"), (payload | {"path": "forbidden"}, "invalid_params"),
                (payload | {"target": target | {"profile_home": "forbidden"}}, "invalid_params"),
                (payload | {"target": target | {"board_id": "other"}}, "stale_generation")):
            with pytest.raises(RuntimeStoreError, match=reason):
                send(changed)
        assert asyncio.run(call(connection, scope, "list_tasks", target=target)) == []
