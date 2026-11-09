"""Scoped send claims and exact claim-token settlement; no POST within a transaction."""

import json
import uuid
from datetime import timedelta
from sqlalchemy import or_, select
from hermes_db.domains.metrics.postgres.queries import metrics as repo
from hermes_db.tables.metrics import packages
from hermes_db.domains.metrics.postgres.operations.consent import gate


def pending():
    return or_(packages.c.send_state.is_(None), packages.c.send_state == "pending")


def freeze_identity(conn, store, row):
    try:
        payload = json.loads(row["payload_json"])
    except (TypeError, ValueError):
        reason, identity = "unreadable payload", None
    else:
        identity = payload.get("install_id") if isinstance(payload, dict) else None
        reason = None if isinstance(identity, str) and identity.strip() else "payload has no usable install_id"
    if reason is not None:
        repo.change_package(conn, store, packages, row["package_id"], dict(send_state="rejected", last_error=reason))
        return None
    repo.change_package(conn, store, packages, row["package_id"], dict(sent_install_id=identity))
    return identity


def claim(conn, store, now, seen):
    from hermes_cli.observability.shared_metrics import _isoformat
    from hermes_cli.observability.shared_metrics_sender import MAX_SEND_ATTEMPTS, _CLAIM_LEASE_SECONDS
    stmt = select(packages).where(repo.scope(packages, store), packages.c.exported_at.is_not(None), pending(),
        or_(packages.c.next_attempt_at.is_(None), packages.c.next_attempt_at <= _isoformat(now)), gate(), packages.c.send_attempts < MAX_SEND_ATTEMPTS)
    if seen:
        stmt = stmt.where(packages.c.package_id.not_in(sorted(seen)))
    row = conn.execute(stmt.order_by(packages.c.created_at, packages.c.package_id).limit(1).with_for_update()).mappings().one_or_none()
    if row is None:
        return None
    row = repo.record(row)
    identity = row["sent_install_id"] or freeze_identity(conn, store, row)
    if identity is None:
        return dict(package_id=row["package_id"], skip=True)
    token = str(uuid.uuid4())
    repo.change_package(conn, store, packages, row["package_id"], dict(send_state="pending", send_attempts=row["send_attempts"] + 1,
        next_attempt_at=_isoformat(now + timedelta(seconds=_CLAIM_LEASE_SECONDS)), claim_token=token))
    return dict(package_id=row["package_id"], payload_json=row["payload_json"], derived=identity, claim_token=token, skip=False)


def mark(conn, store, package_id, token, columns):
    allowed = {"send_state", "sent_at", "last_error", "next_attempt_at"}
    if not columns.keys() <= allowed:
        raise ValueError("Unsupported send settlement columns")
    conditions = [pending()]
    if token is not None:
        conditions.append(packages.c.claim_token == token)
    return repo.change_package(conn, store, packages, package_id, columns, *conditions)


def renew(conn, store, package_id, token, now):
    from hermes_cli.observability.shared_metrics import _isoformat
    from hermes_cli.observability.shared_metrics_sender import _CLAIM_LEASE_SECONDS
    if token is None:
        return False
    return repo.change_package(conn, store, packages, package_id, dict(next_attempt_at=_isoformat(now + timedelta(seconds=_CLAIM_LEASE_SECONDS))),
        pending(), packages.c.claim_token == token, packages.c.next_attempt_at > _isoformat(now)) == 1
