"""Reserve child identity on the verified parent's receipted operation stream."""

from functools import partial
import secrets

from sqlalchemy import func, select

from hermes_db.operations.effects import CoreEffect
from hermes_db.domains.sessions.postgres.operations.sessions import create_on_connection
from hermes_db.domains.sessions.postgres.queries import sessions
from hermes_db.repositories.worker_retirement import descendant_condition
from hermes_db.tables.runtime import worker_executions
from hermes_state_runtime import RuntimeStoreError, _secret_digest
from hermes_state_runtime_workers import CHILD_SEPARATOR


def reservation_effect(*, epoch, execution_id, identity, principal, limits, refused=None):
    return CoreEffect(partial(reserve, epoch=epoch, execution_id=execution_id, identity=dict(identity),
                              principal=principal, limits=limits, refused=refused))


def reserve(conn, scope, session_id, payload, *, epoch, execution_id, identity, principal, limits, refused):
    from hermes_state_ids import new_session_id
    from hermes_state_keys import admission_fingerprint

    secret = payload.get("secret")
    if set(payload) != {"secret"} or not isinstance(secret, str) or not 16 <= len(secret) <= 256:
        raise RuntimeStoreError("invalid_params")
    max_children, max_depth = limits
    prefix = execution_id + CHILD_SEPARATOR
    remainder = func.substr(worker_executions.c.execution_id, len(prefix) + 1)
    slash = func.instr(remainder, "/") if conn.dialect.name == "sqlite" else func.strpos(remainder, "/")
    live = conn.scalar(select(func.count()).select_from(worker_executions).where(
        worker_executions.c.store_id == scope.require_store_id(), descendant_condition(execution_id),
        slash == 0, worker_executions.c.status != "terminal"))
    if refused is None and prefix.count(CHILD_SEPARATOR) > max_depth:
        refused = "delegation_depth_exceeded"
    if refused is None and live >= max_children:
        refused = "delegation_capacity"
    if refused is not None:
        return {"refused": refused}
    parent = sessions.raw_session(conn, scope, session_id)
    child_sid, child_eid = new_session_id(), prefix + secrets.token_hex(8)
    create_on_connection(conn, scope, child_sid, "subagent", model_config={"_delegate_from": session_id},
                         parent_session_id=session_id, profile_name=parent["profile_name"])
    child_scope = dict(identity, session_id=child_sid, execution_id=child_eid, generation=0, secret=secret)
    claim = admission_fingerprint(canonical_target=child_sid, payload=child_scope | {"principal": principal})
    conn.execute(worker_executions.insert().values(store_id=scope.require_store_id(), execution_id=child_eid,
        session_id=child_sid, kind="child", owner_epoch=epoch, generation=0, status="running", adoption_digest=_secret_digest(claim)))
    return {"child": {"session_id": child_sid, "execution_id": child_eid, "generation": 0}}
