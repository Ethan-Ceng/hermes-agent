"""Signature dedup, incident lifecycle and queries within the Cron scope."""

from sqlalchemy import func, select, update

from hermes_db.domains.cron.postgres.queries import cron as repo
from hermes_db.tables.cron import cron_incidents as incidents
from hermes_db.core.values import encode_text


def upsert_incident(resource, job_id, error, *, job_name=None, failure_type=None, output_file=None):
    from cron import incidents as inc
    job_id = str(job_id or "")
    sig = inc._error_signature(job_id, error)
    incident_id, now = inc._incident_id(job_id, sig), inc._hermes_now().isoformat()
    values = {"last_seen_at": now, "error": inc._redact_error(error),
              "output_file": str(output_file) if output_file is not None else None}
    with repo.write(resource) as conn:
        row = repo.fetch(conn, incidents, resource.scope, incident_id)
        if row is not None:
            reopen = row["state"] == "resolved"
            if reopen:
                values.update(state="detected", alerted_at=None, closed_at=None)
            conn.execute(update(incidents).where(repo.key(incidents, resource.scope, incident_id)).values(**repo.encode(values)))
            return incident_id, reopen
        values.update(id=incident_id, job_id=job_id, error_sig=sig, state="detected", first_seen_at=now,
                      failure_type=failure_type or inc._classify_failure_type(error))
        conn.execute(incidents.insert().values(store_id=resource.scope.require_store_id(), **repo.encode(values)))
        return incident_id, True


def set_incident_state(resource, incident_id, state):
    from cron import incidents as inc
    if state not in inc.INCIDENT_STATES:
        return False
    now = inc._hermes_now().isoformat()
    with repo.write(resource) as conn:
        row = repo.fetch(conn, incidents, resource.scope, incident_id)
        if row is None or row["state"] == "closed":
            return False
        values = {"state": state}
        if state == "alerted":
            values["alerted_at"] = now
        elif row["state"] == state:
            return False
        elif state == "closed":
            values.update(closed_at=now, acked_at=now)
        conn.execute(update(incidents).where(repo.key(incidents, resource.scope, incident_id)).values(**values))
        return True


def close_incidents_for_recovered_job(resource, job_id):
    from cron import incidents as inc
    now = inc._hermes_now().isoformat()
    with repo.write(resource) as conn:
        return conn.execute(update(incidents).where(repo.scoped(incidents, resource.scope),
            incidents.c.job_id == encode_text(str(job_id or "")), incidents.c.state.in_(("detected", "alerted")))
            .values(state="resolved", closed_at=now)).rowcount


def list_incidents(resource, state=None):
    from cron import incidents as inc
    if state is not None and state not in inc.INCIDENT_STATES:
        return []
    query = select(incidents).where(repo.scoped(incidents, resource.scope))
    if state is not None:
        query = query.where(incidents.c.state == state)
    with resource.read() as conn:
        return repo.rows(conn, query.order_by(incidents.c.last_seen_order.desc(), incidents.c.last_seen_at.desc(), incidents.c.id.desc()))


def get_incident(resource, incident_id):
    with resource.read() as conn:
        return repo.fetch(conn, incidents, resource.scope, incident_id)


def count_incidents(resource, state=None):
    from cron import incidents as inc
    if state is not None and state not in inc.INCIDENT_STATES:
        return 0
    query = select(func.count()).select_from(incidents).where(repo.scoped(incidents, resource.scope))
    if state is not None:
        query = query.where(incidents.c.state == state)
    with resource.read() as conn:
        return conn.scalar(query)
