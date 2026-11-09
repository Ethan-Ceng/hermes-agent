"""A discarded turn's transcript boundary on the settlement's held Core connection."""

import time

from sqlalchemy import select

from hermes_db.domains.sessions.postgres.support.message_codec import codec
from hermes_db.domains.sessions.postgres.operations.messages import append_on_connection
from hermes_db.domains.sessions.postgres.queries import lineage, messages, sessions
from hermes_db.tables.conversations import messages as table


def close_discarded(conn, scope, row, notice=None, *, replace_after=None, display_metadata=None):
    from agent.turn_failure_copy import FAILED_TURN_DISPLAY_KIND, PARTIAL_FAILED_TURN_NOTICE
    target = sessions.compression_tip(conn, scope, lineage.physical_target(conn, scope, row["target_session_id"]))
    tail = conn.execute(select(table.c.role, table.c.tool_calls, table.c.id, table.c.display_kind).where(
        messages.where(scope, [target]), table.c.active == 1, table.c.role.not_in(("session_meta", "system")))
        .order_by(table.c.id.desc()).limit(1)).mappings().first()
    if (notice is not None and type(replace_after) is int and tail is not None and tail["role"] == "assistant"
            and tail["display_kind"] == FAILED_TURN_DISPLAY_KIND and tail["id"] > replace_after):
        messages.update_row(conn, scope, target, tail["id"], {
            "content": notice, "display_metadata": codec._encode_display_metadata(display_metadata)})
        return True
    if notice is None and (tail is None or not (tail["role"] == "user"
            or (tail["role"] == "assistant" and tail["tool_calls"] not in (None, "", "[]")))):
        return False
    boundary = {"role": "assistant", "content": notice or PARTIAL_FAILED_TURN_NOTICE,
                "timestamp": time.time(), "display_kind": FAILED_TURN_DISPLAY_KIND}
    if display_metadata:
        boundary["display_metadata"] = display_metadata
    append_on_connection(conn, scope, target, [boundary])
    return True
