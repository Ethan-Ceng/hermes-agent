"""Compose one PG session context and concrete components with narrow callbacks."""

def create_session_store(transactions, scope):
    from hermes_constants import profile_name_for_home
    from hermes_cli.db_scope import OwnedProfileContext
    from hermes_db.domains.sessions.postgres.context import SessionContext, TranscriptLimits, HistoryOwnership, SessionEffects
    from hermes_db.domains.sessions.postgres.catalog import SessionCatalog
    from hermes_db.domains.sessions.postgres.messages import SessionMessages
    from hermes_db.domains.sessions.postgres.history import SessionHistory
    from hermes_db.domains.sessions.postgres.lifecycle import SessionLifecycle
    from hermes_db.domains.sessions.postgres.usage import SessionUsage
    from hermes_db.integration.session_portability import SessionPortability
    from hermes_db.domains.sessions.postgres.support.usage_writer import UsageWriter
    from hermes_db.domains.sessions.postgres.store import PostgresSessionStore

    from hermes_state import (resolved_max_resume_messages, resolved_max_export_messages,
        SessionResumeTooLargeError, SessionExportTooLargeError)
    limits = TranscriptLimits(resolved_max_resume_messages, resolved_max_export_messages,
        SessionResumeTooLargeError, SessionExportTooLargeError)
    profile = OwnedProfileContext(scope)
    from functools import partial
    from gateway.owner_identity import same_owner, owners_agree
    from hermes_state_mutation_binding import _history_row, _owner_user
    from hermes_db.integration.events import emit_deleted
    from hermes_db.integration.profile_lifecycle import purge
    from hermes_db.integration.media_retirement import collect, release
    ownership = HistoryOwnership(_history_row, _owner_user, same_owner, owners_agree)
    effects = SessionEffects(partial(emit_deleted, profile), purge, collect, release)
    context = SessionContext(transactions, scope, own_profile=profile_name_for_home(scope.profile_home), profile=profile, transcript_limits=limits, ownership=ownership, effects=effects, is_context_summary=is_context_summary, routes=SessionRouting(), media=SessionMedia())
    usage = SessionUsage(context)
    context.usage_writer = UsageWriter(usage.update_token_counts, profile)
    catalog = SessionCatalog(context, flush_for_read=usage.flush_for_read, flush_token_counts=usage.flush_token_counts)
    messages = SessionMessages(context, get_session=catalog.get_session)
    history = SessionHistory(context, get_active_message_ids=messages.get_active_message_ids, get_messages_as_conversation=messages.get_messages_as_conversation, list_sessions_rich=catalog.list_sessions_rich, rewind_to_message=messages.rewind_to_message)
    lifecycle = SessionLifecycle(context, flush_for_read=usage.flush_for_read)
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
