"""Content-addressed exact prompt and tools[] snapshots, scoped to a store."""

import hashlib

from sqlalchemy import and_, delete, exists, select
from sqlalchemy.dialects.postgresql import insert

from hermes_db.tables.conversations import sessions, system_prompts
from hermes_db.core.values import encode_text


def store_prompt(conn, scope, prompt):
    if prompt is None:
        return None
    digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    conn.execute(insert(system_prompts).values(store_id=scope.require_store_id(), hash=digest, prompt=encode_text(prompt))
                 .on_conflict_do_update(index_elements=[system_prompts.c.store_id, system_prompts.c.hash],
                                       set_={"prompt": system_prompts.c.prompt}))
    return digest


def prune_prompts(conn, scope):
    referenced = exists(select(1).where(
        sessions.c.store_id == system_prompts.c.store_id,
        (sessions.c.system_prompt_hash == system_prompts.c.hash) | (sessions.c.tool_names == system_prompts.c.hash),
    ))
    candidates = select(system_prompts.c.hash).where(system_prompts.c.store_id == scope.require_store_id(), ~referenced)
    candidates = candidates.with_for_update(skip_locked=True)
    conn.execute(delete(system_prompts).where(and_(system_prompts.c.store_id == scope.require_store_id(),
                                                   system_prompts.c.hash.in_(candidates))))
