"""Explicit runtime media component borrowing the owner context; no pools or session facade."""
import json
from sqlalchemy import select
from hermes_db.domains.sessions.postgres.queries import media, sessions
from hermes_db.tables.runtime import session_admissions as table
from hermes_db.domains.runtime.values import _json

def _compact(raw, request, *, compact_images):
    payload = json.loads(raw)
    data = payload.get('api_turn_v1')
    if not isinstance(data, dict):
        return None
    text = compact_images(payload.get('text'), data.get('media'))
    drop = isinstance(data.get('history'), list) and (not request.startswith('responses:'))
    if text is None and (not drop):
        return None
    return {**payload, 'text': payload.get('text') if text is None else text, 'api_turn_v1': {**data, 'history': None} if drop else data}

class RuntimeMedia:

    def __init__(self, context):
        self._context = context

    def settled_native_media(self):
        from gateway.session_contract import admission_media_references
        with self._context.read() as conn:
            rows = conn.scalars(select(table.c.payload_json).where(table.c.store_id == self._context.scope.require_store_id(), table.c.status == 'terminal').execution_options(yield_per=128))
            return [reference for raw in rows for reference in admission_media_references(json.loads(raw))]

    def release_media(self, references, *, retain_history=True):
        return self._context.session.effects.release_media(self._context.session, references, retain_history=retain_history)

    def retire_refused_media(self, references):
        with self._context.write() as conn:
            sessions.lock_store(conn, self._context.scope, exclusive=True)
            media.retire_admission(conn, self._context.scope, references)
        self._context.collect_retired_media()

    def compact_api_payloads(self, admission_id=None):
        cursor, total = (0, 0)
        while True:
            with self._context.write() as conn:
                sessions.lock_store(conn, self._context.scope, exclusive=True)
                query = select(table.c.seq, table.c.admission_id, table.c.payload_json, table.c.request_id).where(table.c.store_id == self._context.scope.require_store_id(), table.c.principal_id == 'api', table.c.status == 'terminal', table.c.seq > cursor).order_by(table.c.seq).limit(128)
                if admission_id is not None:
                    query = query.where(table.c.admission_id == admission_id)
                rows = conn.execute(query).all()
                for seq, row_id, raw, request in rows:
                    cursor = seq
                    payload = _compact(raw, request, compact_images=self._context.session.media.compact_images)
                    if payload is not None:
                        conn.execute(table.update().where(table.c.store_id == self._context.scope.require_store_id(), table.c.admission_id == row_id, table.c.status == 'terminal').values(payload_json=_json(payload)))
                        total += 1
            if len(rows) < 128:
                return total
