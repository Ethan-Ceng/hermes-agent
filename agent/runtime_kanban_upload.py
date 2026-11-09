"""Keep large bytes outside the JSON receipt slot; each prepared chunk is retryable."""

import base64
import hashlib
import inspect
from uuid import uuid4


def upload_attachment(proxy, args, kwargs):
    from agent.runtime_session_store import call_off_event_loop
    from gateway.session_worker_kanban_upload import CHUNK_BYTES
    from hermes_cli import kanban_db as kb
    from hermes_db.integration.kanban_wire import pack, unpack, CommandRefusal
    bound = inspect.signature(kb.store_attachment_bytes).bind(proxy, *args, **kwargs)
    fields = bound.arguments
    data = fields["data"]
    maximum = fields.get("max_bytes")
    maximum = kb.KANBAN_ATTACHMENT_MAX_BYTES if maximum is None else min(maximum, kb.KANBAN_ATTACHMENT_MAX_BYTES)
    if len(data) > maximum:
        raise kb.AttachmentTooLarge(f"attachment exceeds {maximum // (1024 * 1024)} MB limit")
    upload_id, digest = uuid4().hex, hashlib.sha256(data).hexdigest()
    target = {"board": proxy.slug, "board_id": proxy.board_id}
    for index in range(max(1, (len(data) + CHUNK_BYTES - 1) // CHUNK_BYTES)):
        payload = {"target": target, "upload_id": upload_id, "size": len(data), "sha256": digest, "index": index,
                   "data": base64.b64encode(data[index * CHUNK_BYTES:(index + 1) * CHUNK_BYTES]).decode("ascii")}
        call_off_event_loop(proxy.worker_store.kanban_command, "attachment.chunk", payload)
    options = {key: fields[key] for key in ("content_type", "uploaded_by", "board", "max_bytes") if key in fields}
    payload = {"target": target, "args": pack([fields["task_id"], fields["filename"], upload_id, len(data), digest]),
               "kwargs": pack(options)}
    result = unpack(call_off_event_loop(proxy.worker_store.kanban_command, "attachment.commit", payload))
    if isinstance(result, CommandRefusal):
        result.raise_error()
    return result
