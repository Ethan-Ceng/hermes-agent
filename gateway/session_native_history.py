"""Resume current native transcripts; SQLite migration remains in its own path."""

from dataclasses import asdict, replace
from datetime import datetime
import json

from gateway.config import Platform
from gateway.session import SessionEntry
from hermes_state_runtime import RuntimeStoreError

LOCAL_SOURCES = frozenset({"cli", "tui", "gui", "desktop", "oneshot", "tool", "acp"})


def current_launch_params(row):
    from hermes_state_gateway import SessionGatewayMixin
    from hermes_state_sessions import _parse_model_config
    params = {k: row[k] for k in ("model", "cwd") if row.get(k)}
    params['source'] = 'gui' if row['source'] == 'desktop' else row['source']
    saved = _parse_model_config(row.get('model_config'))
    reasoning = saved.get('reasoning_config')
    if isinstance(reasoning, dict):
        params['reasoning'] = 'none' if reasoning.get('enabled') is False else reasoning.get('effort')
        if params['reasoning'] is None:
            del params['reasoning']
    if saved.get('service_tier'):
        params['service_tier'] = saved['service_tier']
    route = SessionGatewayMixin.session_gateway_runtime(row)
    params.update({k: route[k] for k in ('provider', 'base_url') if route.get(k)})
    if row.get('title') == 'Bot Chat':
        params = {k: v for k, v in params.items() if k in ('cwd', 'source')}
        params['follow_profile_config'] = True
        return params, None
    return params, route.get('api_mode')


def resumable_current_row(row, subject):
    from gateway.owner_identity import same_owner
    return (row.get("source") in LOCAL_SOURCES
        and not any(row.get(k) for k in ("session_key", "chat_id", "origin_json"))
        and (not row.get("user_id") or same_owner(row["user_id"], subject)))


def resolve_native_target(authority, actor, row):
    from gateway.session_contract import SessionRef
    from gateway.session_local_recovery import restore_local_session
    from hermes_db.integration.runtime_access import runtime_for_store
    from hermes_state_local import POLICY_PREFIX
    db, sid = authority.db, row['id']
    bound = db.get_meta(POLICY_PREFIX + (row.get('chat_id') or sid)) is not None
    if bound and row.get('chat_id') and runtime_for_store(db).local_owner(sid) != row['chat_id']:
        raise RuntimeStoreError('storage_unavailable')
    if bound or str(row.get('chat_id') or '').startswith('local-'):
        ref = SessionRef(authority.profile_id, row['chat_id'])
        authority.authorize(actor, ref, 'session:read')
        return restore_local_session(authority, ref.session_id) if bound else ref
    return resume_current_history(authority, actor, row)


def resume_current_history(authority, actor, row):
    from gateway.run import _load_gateway_config
    from gateway.session_local_recovery import local_source, restore_local_session
    from gateway.session_policy import build_policy, bind_launch_key
    from hermes_db.integration.authority_access import authorize_history
    from hermes_db.health import persisted_profile_id
    from hermes_db.integration.runtime_access import runtime_for_store
    if actor.profile_id != authority.profile_id:
        raise RuntimeStoreError("profile_mismatch")
    native = getattr(authority, "_native_legacy_transports", {}).get(actor.transport_id) == actor
    if not native or not {"session:read", "session:create"} <= actor.capabilities:
        raise RuntimeStoreError("permission_denied")
    if row["source"] not in LOCAL_SOURCES or not authorize_history(authority, actor, row["id"]):
        raise RuntimeStoreError("permission_denied")
    authority._require_admission_open()
    sid = row["id"]
    params, api_mode = current_launch_params(row)
    config, secrets = _load_gateway_config(), {}
    policy = build_policy(params, config, private_secrets=secrets)
    if api_mode:
        config = json.loads(policy.config_json)
        config.setdefault('model', {})['api_mode'] = api_mode
        policy = replace(policy, config_json=json.dumps(config))
    policy = bind_launch_key(authority, sid, policy, None, config_secrets=secrets)
    source = local_source(authority, sid, actor.subject)
    route = authority.runner.session_store._generate_session_key(source)
    now = datetime.fromtimestamp(row["started_at"])
    entry = SessionEntry(route, sid, now, now, origin=source, platform=Platform.LOCAL)
    receipt = dict(profile_id=persisted_profile_id(authority), principal_id=actor.subject, request_id="history:" + sid,
        session_id=sid, history_session_id=sid, lineage=[sid], route=route, entry=entry.to_dict(), policy=asdict(policy))
    runtime_for_store(authority.db).promote_current_history(epoch=authority.epoch, actor=actor,
        receipt=receipt, native_transport=native)
    return restore_local_session(authority, sid)
