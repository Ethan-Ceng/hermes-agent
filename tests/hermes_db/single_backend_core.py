"""One process exercises the real public domains; files hold only test IDs, never read substitutes."""

from contextlib import closing
from pathlib import Path
from datetime import datetime, UTC


def conversations(home, label, role, saved):
    from hermes_cli.db_sessions import open_session_store
    with closing(open_session_store(home / "state.db")) as store:
        if role == "write":
            store.create_session("same", "cli", system_prompt="frozen " + label)
            store.append_message("same", "user", label)
        assert store.get_session("same")["system_prompt"] == "frozen " + label
        assert store.get_messages_as_conversation("same")[0]["content"] == label


def projects(home, label, role, saved):
    from hermes_cli import projects_db as projects
    with projects.connect_closing() as store:
        if role == "write":
            saved["project"] = projects.create_project(store, name=label, slug="same", folders=[str(home / "workspace")])
            projects.set_active(store, saved["project"])
        project = projects.get_project(store, "same")
        assert project.id == saved["project"] and project.name == label
        assert projects.get_active_id(store) == project.id


def evidence(home, label, role, saved):
    from agent import verification_evidence as evidence
    workspace = home / "workspace"
    if role == "write":
        evidence.record_terminal_result(command="python -m pytest", cwd=workspace, session_id="same", exit_code=0, output=label)
    result = evidence.verification_status(session_id="same", cwd=workspace)
    assert result["status"] == "passed" and result["evidence"]["output_summary"] == label


def cron(home, label, role, saved):
    from cron import jobs, executions, incidents, notepad, delivery_queue
    if role == "write":
        saved["job"] = jobs.create_job(prompt=label, schedule="every 1h")["id"]
        execution = executions.create_execution("same", source="builtin")
        saved["execution"] = execution["id"]
        executions.mark_execution_running(execution["id"])
        assert executions.finish_execution(execution["id"], success=True)["status"] == "completed"
        saved["incident"], _ = incidents.upsert_incident(saved["job"], label)
        notepad.set_note(saved["job"], "same", label)
        delivery_queue.enqueue("same", {"id": saved["job"], "label": label}, label)
    assert executions.get_execution(saved["execution"])["status"] == "completed"
    assert incidents.get_incident(saved["incident"])["job_id"] == saved["job"]
    assert notepad.get_note(saved["job"], "same") == label
    assert jobs.get_job(saved["job"])["prompt"] == label
    if role == "read":
        before = delivery_queue.get_status("same")["status"]
        delivered = []
        delivery_queue.drain(lambda job, content, failure: delivered.append((job["label"], content)))
        assert delivered == ([(label, label)] if before == "pending" else [])
        assert delivery_queue.get_status("same")["status"] == "delivered"


def kanban(home, label, role, saved):
    from hermes_cli import kanban_db as kb, kanban_db_connect as connection
    for slug in ("alpha", "beta"):
        if role == "write":
            kb.create_board(slug)
        with connection.connect_closing(board=slug) as board:
            if role == "write":
                task = kb.create_task(board, title=label + slug, workspace_kind="dir", workspace_path=str(home / "workspace"))
                saved[slug] = task
                kb.claim_task(board, task)
                kb.add_comment(board, task, "worker", label)
                saved[slug + "-attachment"] = kb.store_attachment_bytes(board, task, "proof.txt", label.encode())
                assert kb.complete_task(board, task, result=label)
            task = saved[slug]
            assert kb.get_task(board, task).title == label + slug
            assert kb.get_task(board, task).status == "done"
            assert [comment.body for comment in kb.list_comments(board, task)] == [label]
            attachment = kb.get_attachment(board, saved[slug + "-attachment"])
            assert Path(attachment.stored_path).read_bytes() == label.encode()
            assert kb.latest_run(board, task).outcome == "completed"


def rooms(home, label, role, saved):
    from gateway import hosted_rooms as rooms
    from gateway.hosted_room_attachments import HostedRoomAttachmentStore
    location = rooms.default_db_path()
    attachments = HostedRoomAttachmentStore(location)
    if role == "write":
        rooms.create_room(location, room_id="same", name=label, members=[{"id": "ops"}], authority_gateway_id="owner")
        saved["image"] = attachments.put(room_id="same", upload_id="same", kind="image", name="proof.png", mime="image/png", data=b"\x89PNG\r\n\x1a\n" + label.encode())["attachment_id"]
        image = attachments.find_upload(room_id="same", upload_id="same")
        manifest = [{key: image[key] for key in ("attachment_id", "kind", "name", "size", "mime")}]
        attachments.commit_message(room_id="same", event_id="same", manifest=manifest, recipient_member_ids=["ops"])
        rooms.append_event(location, room_id="same", event_id="same", kind="message.user", actor={"kind": "user", "id": "user"}, payload={"text": label}, authority_gateway_id="owner", authority_epoch=1)
    events = rooms.read_events(location, room_id="same")["events"]
    assert events[0]["payload"]["text"] == label
    assert attachments.read(room_id="same", attachment_id=saved["image"], event_id="same", recipient_member_id="ops").data.endswith(label.encode())


def metrics(home, label, role, saved):
    from hermes_cli.observability.shared_metrics import SharedMetricsStore
    from hermes_cli.observability.shared_metrics_contract import CLIENT_ACTIVE_METRIC, client_resource
    store = SharedMetricsStore.create() if role == "write" else SharedMetricsStore()
    if role == "write":
        resource = client_resource("0.0.0", os_name="", architecture="", install_method="git")
        store.record_counter(CLIENT_ACTIVE_METRIC, {}, resource)
    assert store.counter_snapshot()[0]["value"] == 1


def plugins(home, label, role, saved):
    from plugins.plugin_storage import plugin_store
    from plugins.platforms.discord.recovery import DiscordRecoveryStore
    for plugin in ("discord", "other"):
        store = plugin_store(plugin, namespace="same")
        if role == "write":
            store.put("same", label + plugin, expected_revision=0)
        assert store.get("same").value == label + plugin
    discord = DiscordRecoveryStore()
    if role == "write":
        stamp = datetime.now(UTC).isoformat()
        discord.attempt(dict(message_id="322", channel_id="123", thread_id=None, parent_channel_id=None, author_id="42", created_at=stamp, status="queued", updated_at=stamp), error=None)
        discord.response("322", response_id=label, completed=True, now=stamp)
    assert discord.is_complete("322") and discord.cursor("123") == "322"


DOMAINS = (conversations, projects, evidence, cron, kanban, rooms, metrics, plugins)
