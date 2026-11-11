"""Bounded surviving-reference queries over one supplied Connection and scope."""

import json
from pathlib import Path
from sqlalchemy import select
from hermes_db.tables.runtime import session_admissions
from hermes_db.domains.sessions.postgres.queries import media

def history(conn, scope, references, *, spillover_names):
    needles, mentioned, spill_names = ({}, set(), set())
    for reference in references:
        for sep in ('/', '\\'):
            tail = reference['sha256'] + sep + Path(reference['path']).name
            needles[tail] = needles[json.dumps(tail)[1:-1]] = reference['path']
    matched = 0
    for content, api in media.text_rows(conn, scope):
        text = content.decode('utf-8', 'replace') if isinstance(content, bytes) else str(content)
        spill_names |= spillover_names(text, api)
        mentioned.update((raw for needle, raw in needles.items() if needle in text or needle in (api or '')))
        matched += int('spillover' in text or bool(needles))
        if matched > 20000:
            return (None, None)
    return (mentioned, spill_names)


def held_payloads(conn, scope):
    return conn.execute(select(session_admissions.c.status, session_admissions.c.request_id, session_admissions.c.payload_json)
        .where(session_admissions.c.store_id == scope.require_store_id()).execution_options(yield_per=512))
