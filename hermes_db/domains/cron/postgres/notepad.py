"""A job lock protects quota accounting and mutation in the same transaction."""

from contextlib import contextmanager

from sqlalchemy import and_, delete, func, select
from sqlalchemy.dialects.postgresql import insert

from hermes_db.tables.cron_notepad import cron_notepad as notes, cron_notepad_locks as locks
from hermes_db.core.values import decode_text, encode_text


def _job(table, resource, job_id):
    return and_(table.c.store_id == resource.scope.require_store_id(), table.c.job_id == encode_text(str(job_id)))


@contextmanager
def _write(resource, job_id):
    with resource.write() as conn:
        conn.execute(insert(locks).values(store_id=resource.scope.require_store_id(), job_id=encode_text(str(job_id)))
                     .on_conflict_do_nothing())
        conn.execute(select(locks.c.job_id).where(_job(locks, resource, job_id)).with_for_update()).one()
        yield conn


def set_note(resource, job_id, key, value):
    notepad = resource.notes
    job_id, key, value = str(job_id), str(key), str(value)
    notepad.validate(job_id, key, value)
    now = notepad.now().isoformat()
    with _write(resource, job_id) as conn:
        size = conn.scalar(select(func.coalesce(func.sum(func.octet_length(notes.c.key) + func.octet_length(notes.c.value)), 0))
                           .where(_job(notes, resource, job_id), notes.c.key != encode_text(key)))
        if size + len(key.encode("utf-8")) + len(value.encode("utf-8")) > notepad.max_job_total_bytes:
            raise ValueError(f"notepad full: job '{job_id}' would exceed {notepad.max_job_total_bytes} bytes total; delete unused keys first")
        query = insert(notes).values(store_id=resource.scope.require_store_id(), job_id=encode_text(job_id),
                                   key=encode_text(key), value=encode_text(value), updated_at=now)
        conn.execute(query.on_conflict_do_update(index_elements=list(notes.primary_key.columns),
            set_={"value": query.excluded.value, "updated_at": query.excluded.updated_at}))
    return {"job_id": job_id, "key": key, "value": value, "updated_at": now}


def get_note(resource, job_id, key):
    with resource.read() as conn:
        return decode_text(conn.scalar(select(notes.c.value).where(_job(notes, resource, job_id), notes.c.key == encode_text(str(key)))))


def delete_note(resource, job_id, key):
    with _write(resource, job_id) as conn:
        return conn.execute(delete(notes).where(_job(notes, resource, job_id), notes.c.key == encode_text(str(key)))).rowcount > 0


def list_notes(resource, job_id):
    with resource.read() as conn:
        rows = conn.execute(select(notes).where(_job(notes, resource, job_id)).order_by(notes.c.key)).mappings()
        return [{"job_id": decode_text(row["job_id"]), "key": decode_text(row["key"]),
                 "value": decode_text(row["value"]), "updated_at": row["updated_at"]} for row in rows]


def clear_notepad(resource, job_id):
    with _write(resource, job_id) as conn:
        return conn.execute(delete(notes).where(_job(notes, resource, job_id))).rowcount
