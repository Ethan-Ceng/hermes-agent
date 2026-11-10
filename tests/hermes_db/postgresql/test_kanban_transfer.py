"""PG Board archives are portable snapshots with real files and no SQLite payload."""

import hashlib
import json
import shutil
import tarfile
from pathlib import Path
import pytest

from hermes_cli import kanban_db as kb, kanban_db_connect as kbc, kanban_db_notify as notify, kanban_transfer as transfer

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def test_pg_export_has_consistent_history_files_and_scrubbed_runtime(pg_profiles, tmp_path, monkeypatch):
    with pg_profiles("one"):
        kb.create_board("exported", name="Export🙂")
        with kbc.connect_closing(board="exported") as store:
            task = kb.create_task(store, title="running🙂", session_id="private-session", workspace_kind="dir", workspace_path=str(tmp_path))
            claim = kb.claim_task(store, task)
            kb.add_comment(store, task, "worker", "exact🙂\x00")
            attachment = kb.store_attachment_bytes(store, task, "proof.bin", b"binary\x00proof")
            notify.add_notify_sub(store, task_id=task, platform="telegram", chat_id="private-chat")
            original = shutil.copyfileobj
            copied = []

            def copy(*args, **kwargs):
                assert store._transactions.engine.pool.checkedout() == 0
                copied.append(True)
                return original(*args, **kwargs)

            monkeypatch.setattr(shutil, "copyfileobj", copy)
            result = transfer.export_board("exported", str(tmp_path / "board-export"))
            assert copied
            assert kb.get_task(store, task).current_run_id == claim.current_run_id
            assert kb.get_task(store, task).status == "running"
            assert Path(kb.get_attachment(store, attachment).stored_path).read_bytes() == b"binary\x00proof"
        with tarfile.open(result["archive"]) as archive:
            assert not any(name.endswith(".db") for name in archive.getnames())
            manifest = json.load(archive.extractfile("exported/manifest.json"))
            payload = json.load(archive.extractfile("exported/data.json"))
            assert manifest["format_version"] == 2 and manifest["backend"] == "postgresql"
            imported = payload["tables"]["tasks"][0]
            assert imported["id"] == task and imported["status"] == "ready"
            assert imported["claim_lock"] is None and imported["current_run_id"] is None
            assert imported["session_id"] is None and imported["workspace_path"] is None
            assert payload["tables"]["task_runs"][0]["status"] == "released"
            assert payload["tables"]["task_comments"][0]["body"] == "exact🙂\x00"
            assert "kanban_notify_subs" not in payload["tables"]
            member, proof = next(iter(manifest["files"].items()))
            content = archive.extractfile("exported/" + member).read()
            assert content == b"binary\x00proof" and hashlib.sha256(content).hexdigest() == proof["sha256"]


def make_archive(pg_profiles, tmp_path):
    with pg_profiles("one"), kbc.connect_closing() as source:
        parent = kb.create_task(source, title="parent🙂", body="exact\x00body")
        from hermes_cli import kanban_db_workspace as workspace
        directory = kb.workspaces_root() / parent
        directory.mkdir(parents=True)
        workspace.set_workspace_path(source, parent, directory)
        artifact = directory / "proof.bin"
        artifact.write_bytes(b"retained\x00bytes")
        assert kb.complete_task(source, parent, summary="delivered🙂",
            metadata={"zero": 0, "false": False, "artifacts": [str(artifact)]})
        child = kb.create_task(source, title="directory worker", parents=[parent], workspace_kind="dir", workspace_path=str(tmp_path))
        kb.claim_task(source, child)
        kb.add_comment(source, parent, "author", "comment\x00🙂")
        archive = transfer.export_board("default", str(tmp_path / "portable"))["archive"]
        return archive, parent, child, kb.latest_run(source, parent).id


def test_pg_import_persists_complete_graph_history_files_and_separate_generation(pg_profiles, tmp_path):
    archive, parent, child, old_run = make_archive(pg_profiles, tmp_path)
    with pg_profiles("two"):
        imported = transfer.import_board(archive, "restored", activate=True)
        assert imported["board"] == "restored" and imported["tasks_parked"] == 1
        with kbc.connect_closing(board="restored") as store:
            assert kb.get_task(store, parent).body == "exact\x00body"
            assert kb.get_task(store, child).status == "triage"
            assert kb.get_task(store, child).workspace_path is None
            assert kb.parent_ids(store, child) == [parent]
            run = kb.latest_run(store, parent)
            assert run.id != old_run and {key: run.metadata[key] for key in ("zero", "false")} == {"zero": 0, "false": False}
            assert kb.list_comments(store, parent)[0].body == "comment\x00🙂"
            attachment, = kb.list_attachments(store, parent)
            assert Path(attachment.stored_path).read_bytes() == b"retained\x00bytes"
            assert run.metadata["artifacts"] == [attachment.stored_path]
            assert Path(attachment.stored_path).is_relative_to(kb.attachments_root(board="restored"))
            assert notify.list_notify_subs(store) == []
            board_id = store.board_id
        duplicate = transfer.import_board(archive, "restored")
        assert duplicate["board"] == "restored-2" and duplicate["renamed"]
        with kbc.connect_closing(board="restored-2") as separate:
            assert separate.board_id != board_id and kb.get_task(separate, parent).status == "done"
    with pg_profiles("two"), kbc.connect_closing(board="restored") as reopened:
        assert kb.get_task(reopened, parent).title == "parent🙂"
    with pg_profiles("one"), kbc.connect_closing() as source:
        assert kb.get_task(source, child).status == "running"


def test_pg_import_rolls_back_board_graph_and_its_exclusive_stage(pg_profiles, tmp_path, monkeypatch):
    from hermes_db.integration.transfer import kanban as core
    archive, _parent, _child, _run = make_archive(pg_profiles, tmp_path)
    with pg_profiles("two") as home:
        original, calls = core.insert_import_row, []

        def fail(*args, **kwargs):
            value = original(*args, **kwargs)
            calls.append(True)
            assert not kb.board_exists("broken")
            if len(calls) == 3:
                raise RuntimeError("test atomic import failed")
            return value

        with monkeypatch.context() as fault:
            fault.setattr(core, "insert_import_row", fail)
            with pytest.raises(RuntimeError, match="atomic import failed"):
                transfer.import_board(archive, "broken")
        assert not kb.board_exists("broken")
        assert list((home / "kanban" / "imports").iterdir()) == []
        assert transfer.import_board(archive, "broken")["board"] == "broken"


@pytest.mark.parametrize("failure", ["after_commit", "file_io"])
def test_original_import_job_recovers_without_reimporting_graph(pg_profiles, tmp_path, monkeypatch, failure):
    from contextlib import contextmanager
    from sqlalchemy import select
    from hermes_db.errors import StorageBusyError, UnknownCommitError
    from hermes_cli.db_domains import acquire_profile_domain
    from hermes_db.domains.kanban.postgres import files
    from hermes_db.integration.transfer import kanban as publication
    from hermes_db.tables.kanban_file_jobs import file_jobs
    from hermes_db.core.values import decode_text
    archive, parent, child, _run = make_archive(pg_profiles, tmp_path)
    with pg_profiles("two"), acquire_profile_domain("kanban_tasks") as resource:
        with monkeypatch.context() as fault:
            if failure == "after_commit":
                transactions_type = type(resource._transactions)
                original = transactions_type.write

                @contextmanager
                def lost_ack(transactions, **kwargs):
                    with original(transactions, **kwargs) as conn:
                        yield conn
                    raise UnknownCommitError("test import acknowledgement lost")

                fault.setattr(transactions_type, "write", lost_ack)
                expected = UnknownCommitError
            else:
                def interrupted(*args):
                    raise OSError("test file publication interrupted")
                fault.setattr(publication, "_publish", interrupted)
                expected = OSError
            with pytest.raises(expected):
                transfer.import_board(archive, "recover")
        with resource.read() as conn:
            row = conn.execute(select(file_jobs).where(file_jobs.c.store_id == "two", file_jobs.c.action == "import")).mappings().one()
            board_id, stage = row["board_id"], Path(decode_text(row["stage_root"]))
        assert stage.is_dir()
        with pytest.raises(StorageBusyError, match="pending"):
            with kbc.connect_closing(board="recover"):
                pytest.fail("unpublished Board must not open")
        assert not files.run_job(resource, board_id)["files_pending"]
        assert not files.run_job(resource, board_id)["files_pending"]
        assert not stage.exists()
        with kbc.connect_closing(board="recover") as store:
            assert store.board_id == board_id and len(kb.list_tasks(store)) == 2
            assert kb.parent_ids(store, child) == [parent]
            attachment, = kb.list_attachments(store, parent)
            assert Path(attachment.stored_path).read_bytes() == b"retained\x00bytes"
            assert len(kb.list_runs(store, parent)) == 1


def test_corrupt_attachment_is_rejected_before_importing_any_rows(pg_profiles, tmp_path):
    from hermes_cli.archive_safe import make_targz, safe_extract_targz
    archive, _parent, _child, _run = make_archive(pg_profiles, tmp_path)
    extracted = tmp_path / "tampered"
    safe_extract_targz(Path(archive), extracted)
    root = extracted / "default"
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    member = next(iter(manifest["files"]))
    (root / member).write_bytes(b"tampered")
    corrupted = make_targz(str(tmp_path / "corrupt"), str(extracted), "default")
    with pg_profiles("two") as home:
        with pytest.raises(ValueError, match="fingerprint"):
            transfer.import_board(corrupted, "corrupt")
        assert not kb.board_exists("corrupt")
        assert not (home / "kanban" / "imports").exists()


def test_cyclic_archive_is_rejected_before_target_board_creation(pg_profiles, tmp_path):
    from hermes_cli.archive_safe import make_targz, safe_extract_targz
    archive, parent, child, _run = make_archive(pg_profiles, tmp_path)
    extracted = tmp_path / "cyclic"
    safe_extract_targz(Path(archive), extracted)
    path = extracted / "default" / "data.json"
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    data["tables"]["task_links"].append(dict(data["tables"]["task_links"][0], parent_id=child, child_id=parent))
    path.write_text(json.dumps(data), encoding="utf-8")
    archive = make_targz(str(tmp_path / "cyclic-board"), str(extracted), "default")
    with pg_profiles("two") as home:
        with pytest.raises(ValueError, match="cycle"):
            transfer.import_board(archive, "cyclic")
        assert not kb.board_exists("cyclic")
        assert not (home / "kanban" / "imports").exists()
