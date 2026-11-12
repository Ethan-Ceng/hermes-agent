"""Compose owner session acquisitions from an already resolved Profile configuration."""

from functools import partial
from pathlib import Path

from hermes_db.handle import DatabaseHandle
from hermes_db.scope import DatabaseScope
from hermes_db.settings import DatabaseSettings
from hermes_cli.db_scope import bind_profile_home


def _path(db_path):
    from hermes_constants import get_hermes_home
    return Path(db_path) if db_path is not None else get_hermes_home() / "state.db"


def _owner_only():
    from agent.runtime_session_store import WorkerPersistenceError, is_worker_process
    if is_worker_process():
        raise WorkerPersistenceError("owner_store_access_from_worker")


def acquire_sessions(db_path=None):
    _owner_only()
    from hermes_cli.db_setup import resolve_db_configuration
    from hermes_db.domains.sessions.resource import SessionResource
    path = _path(db_path)
    settings, scope = resolve_db_configuration(path.resolve().parent)
    if settings.backend == "sqlite":
        from hermes_state_registry import acquire
        with bind_profile_home(scope):
            return acquire(None if db_path is None else path)
    return SessionResource(acquire_db(settings, scope))


def open_session_store(db_path=None, *, read_only=False):
    _owner_only()
    from hermes_cli.db_setup import resolve_db_configuration
    from hermes_db.domains.sessions.resource import SessionResource
    path = _path(db_path)
    settings, scope = resolve_db_configuration(path.resolve().parent)
    if settings.backend == "sqlite":
        from hermes_state import SessionDB
        with bind_profile_home(scope):
            return SessionDB.open_existing(db_path=None if db_path is None else path, read_only=read_only)
    return SessionResource(acquire_db(settings, scope))


def session_store_exists(db_path=None):
    """Whether to attempt an open; PG reachability is determined by that open."""
    from hermes_cli.db_setup import storage_backend
    path = _path(db_path)
    if storage_backend(path.resolve().parent) == "postgresql":
        return True
    from hermes_state import _default_db_path
    return (Path(_default_db_path()) if db_path is None else path).exists()


def close_session_resources_under(home):
    from hermes_db.domains.sessions.registry import close_all as close_native
    from hermes_state_registry import close_all_under
    return close_all_under(home) + close_native(home)


def close_session_resources():
    """The gateway calls this only after all producer/worker quiesce checks pass."""
    from hermes_db.infra.postgresql.engine import close_engines
    from hermes_db.domains.sessions.registry import close_all as close_native
    from hermes_state_registry import close_all
    count = close_all() + close_native()
    close_engines()
    return count


def acquire_db(settings: DatabaseSettings, scope: DatabaseScope) -> DatabaseHandle:
    _owner_only()
    if settings.backend == "sqlite":
        from hermes_db.factory import acquire_backend

        backend = acquire_backend(settings, scope, sqlite_path=scope.profile_home / "state.db")
        return acquire_sqlite(backend)
    scope.require_store_id()
    from hermes_db.infra.postgresql.engine import require_postgresql_driver

    require_postgresql_driver()
    from hermes_db.domains.sessions.registry import acquire
    return acquire(settings.postgresql, scope, build=_build_session_resources)


def _native_runtime_function(name):
    """Resolve the existing fixed runtime dispatch at the application facade patch seam."""
    import hermes_state_runtime
    return getattr(hermes_state_runtime, name)


def acquire_sqlite(backend):
    """Assemble native business adapters under their explicitly selected application owner."""
    from hermes_db.domains.resource import _bound_method
    from hermes_db.domains.sessions.sqlite import SQLiteSessions
    from hermes_db.domains.runtime.sqlite import SQLiteRuntime
    from hermes_state_registry import acquire, release

    scope = backend.scope
    activate = partial(bind_profile_home, scope)
    with activate():
        db = acquire(backend.sqlite_path)
    runtime = SQLiteRuntime(db, scope, activate=activate, resolve=_native_runtime_function)
    return DatabaseHandle(scope, SQLiteSessions(db, scope, activate=activate, runtime=runtime),
                          runtime,
                          _bound_method(activate, release, db))



def create_session_store(transactions, scope):
    from hermes_constants import profile_name_for_home
    from hermes_cli.db_scope import OwnedProfileContext
    from hermes_db.domains.sessions.postgres.context import SessionContext, TranscriptLimits, HistoryOwnership, SessionEffects
    from hermes_cli.db_session_lifecycle import OwnedSessionCatalog, OwnedSessionLifecycle, profile_limit
    from hermes_db.domains.sessions.postgres.messages import SessionMessages
    from hermes_db.domains.sessions.postgres.history import SessionHistory
    from hermes_db.domains.sessions.postgres.usage import SessionUsage
    from hermes_db.domains.sessions.postgres.portability import SessionPortability
    from hermes_cli.db_usage_writer import UsageWriter
    from hermes_db.domains.sessions.postgres.store import PostgresSessionStore

    from hermes_state import (resolved_max_resume_messages, resolved_max_export_messages,
        SessionResumeTooLargeError, SessionExportTooLargeError)
    from functools import partial
    profile = OwnedProfileContext(scope)
    limits = TranscriptLimits(partial(profile_limit, profile, resolved_max_resume_messages), partial(profile_limit, profile, resolved_max_export_messages),
        SessionResumeTooLargeError, SessionExportTooLargeError)
    from gateway.owner_identity import same_owner, owners_agree
    from hermes_state_mutation_binding import _history_row, _owner_user
    from hermes_db.domains.sessions.postgres.profile_lifecycle import purge
    from hermes_cli.db_media_retirement import collect, release
    ownership = HistoryOwnership(_history_row, _owner_user, same_owner, owners_agree)
    effects = SessionEffects(partial(emit_deleted, profile), purge, collect, release)
    from hermes_cli.db_runtime import create_runtime_store
    context = SessionContext(transactions, scope, own_profile=profile_name_for_home(scope.profile_home), profile=profile, transcript_limits=limits, ownership=ownership, effects=effects, is_context_summary=is_context_summary, routes=SessionRouting(), media=SessionMedia(), runtime_factory=create_runtime_store, activity_description=activity_description, activity_provenance=activity_provenance, todo_result_limit=todo_result_limit)
    usage = SessionUsage(context)
    context.usage_writer = UsageWriter(usage.update_token_counts, profile)
    catalog = OwnedSessionCatalog(context, flush_for_read=usage.flush_for_read, flush_token_counts=usage.flush_token_counts)
    messages = SessionMessages(context, get_session=catalog.get_session)
    history = SessionHistory(context, get_active_message_ids=messages.get_active_message_ids, get_messages_as_conversation=messages.get_messages_as_conversation, list_sessions_rich=catalog.list_sessions_rich, rewind_to_message=messages.rewind_to_message)
    lifecycle = OwnedSessionLifecycle(context, flush_for_read=usage.flush_for_read)
    portability = SessionPortability(context, flush_for_read=usage.flush_for_read)
    return PostgresSessionStore(context, catalog, messages, history, lifecycle, usage, portability)


def is_context_summary(content):
    from agent.context_compressor import ContextCompressor
    return ContextCompressor._is_context_summary_content(content)


class SessionRouting:
    def branch_values(self):
        from gateway.config import Platform
        from gateway.session import SessionEntry, SessionSource, build_session_key
        from gateway.session_lifecycle import _now
        return Platform, SessionSource, SessionEntry, build_session_key, _now

    def reset_values(self):
        from gateway.session import SessionEntry
        from gateway.session_lifecycle import _now
        return SessionEntry, _now

    def messaging_platform(self, label):
        from gateway.session_route_recovery import _messaging_platform
        return _messaging_platform(label)


class SessionMedia:
    def retire_spillover(self, conn, scope, session_ids):
        from hermes_cli.db_media_retirement import retire_spillover
        return retire_spillover(conn, scope, session_ids)

    def settled_references(self, payload):
        from gateway.session_contract import admission_media_references
        return admission_media_references(payload)

    def admission_references(self, scope, payload, request_id):
        from gateway.session_contract import admission_media_references
        from gateway.session_ingress_media import hosted_document_references
        from hermes_cli.db_scope import bind_profile_home
        with bind_profile_home(scope):
            return [*admission_media_references(payload), *hosted_document_references(request_id, payload),
                    *payload.get("api_turn_v1", {}).get("media", [])]

    def compact_images(self, content, media):
        from gateway.session_api_media import _compacted
        return _compacted(content, media)



import logging


def emit_deleted(profile, session_ids, *, reason, primary=None):
    from hermes_constants import profile_name_for_home
    from hermes_cli.lifecycle import invoke_hook

    ids = sorted(set(session_ids))
    if not ids:
        return
    payload = {"session_id": primary if primary in ids else ids[0], "reason": reason,
               "profile": profile_name_for_home(profile.scope.profile_home)}
    if len(ids) > 1:
        payload["deleted_ids"] = ids
    try:
        with profile.activate():
            invoke_hook("on_session_delete", **payload)
    except Exception:
        logging.getLogger(__name__).exception("Session lifecycle hook failed after committed storage change")


def _construct_store(settings, scope):
    from hermes_db.factory import acquire_backend
    from hermes_db.settings import DatabaseSettings
    from hermes_db.tables.metadata import SCHEMA
    from hermes_db.schema import check_schema
    check_schema(settings)
    backend = acquire_backend(DatabaseSettings("postgresql", settings), scope, schema_token=SCHEMA)
    return create_session_store(backend.transactions, scope)


def _build_session_resources(settings, scope):
    from hermes_cli.db_runtime import create_runtime_store
    store = _construct_store(settings, scope)
    try:
        return store, create_runtime_store(store)
    except BaseException:
        store.close()
        raise


def activity_description(value):
    from agent.session_activity import bound_activity_description
    return bound_activity_description(value)


def activity_provenance(value):
    from agent.session_activity import normalize_activity_provenance
    return normalize_activity_provenance(value).value


def todo_result_limit():
    from tools.todo_tool import MAX_TODO_RESULT_CHARS
    return MAX_TODO_RESULT_CHARS


def sqlite_runtime_for_store(store):
    from functools import partial
    from hermes_db.health import profile_home_for_store
    from hermes_db.scope import DatabaseScope
    from hermes_db.domains.runtime.sqlite import SQLiteRuntime
    from hermes_cli.db_scope import bind_profile_home
    scope = DatabaseScope(profile_home_for_store(store))
    return SQLiteRuntime(store, scope, activate=partial(bind_profile_home, scope), resolve=_native_runtime_function)
