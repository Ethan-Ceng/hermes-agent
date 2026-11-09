"""Durable local-file retirement and scoped surviving-reference snapshots."""

import hashlib
import json

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from hermes_db.domains.sessions.postgres.support.message_codec import content_from_bytes
from hermes_db.domains.sessions.postgres.queries import retirement_fences
from hermes_db.tables.conversations import messages
from hermes_db.tables.runtime import state_meta
from hermes_db.domains.runtime.receipts import RETIRED_MEDIA_PREFIX as PREFIX, MEDIA_SPILLOVER_PREFIX as SPILLOVER_PREFIX


def _candidate(conn, scope, key, value):
    conn.execute(insert(state_meta).values(store_id=scope.require_store_id(), key=key, value=json.dumps(value))
        .on_conflict_do_nothing(index_elements=list(state_meta.primary_key.columns)))


def retire_admission(conn, scope, references):
    for reference in references:
        _candidate(conn, scope, PREFIX + hashlib.sha256(reference["path"].encode()).hexdigest(), reference)


def text_rows(conn, scope, session_ids=None):
    statement = select(messages.c.content, messages.c.api_content).where(messages.c.store_id == scope.require_store_id())
    if session_ids is not None:
        statement = statement.where(messages.c.session_id.in_(session_ids))
    for content, api in conn.execute(statement.execution_options(yield_per=512)):
        yield content_from_bytes(content), bytes(api).decode("utf-8") if api is not None else None


def retire_spillover(conn, scope, session_ids):
    from hermes_db.core.file_scope import identity, owner_id
    from tools.tool_result_storage import spillover_names_in_text
    root = scope.profile_home / "cache" / "spillover"
    owner = owner_id(scope.profile_home, create=True)
    for start in range(0, len(session_ids), 1000):
        for content, api in text_rows(conn, scope, session_ids[start:start + 1000]):
            for name in spillover_names_in_text(content, api):
                try:
                    stamp = identity(root / name)
                except OSError:
                    stamp = None
                _candidate(conn, scope, SPILLOVER_PREFIX + name,
                    {"name": name, "owner": owner, "identity": stamp})


def candidates(conn, scope, prefix):
    return [(key, json.loads(raw)) for key, raw in retirement_fences._prefixed(conn, scope, prefix)]




def forget(conn, scope, keys):
    for start in range(0, len(keys), 1000):
        retirement_fences._delete_meta(conn, scope, keys[start:start + 1000])
