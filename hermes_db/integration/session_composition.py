"""Compose one PG session context and concrete components with narrow callbacks."""

def create_session_store(transactions, scope):
    from hermes_constants import profile_name_for_home
    from hermes_db.integration.profile_context import OwnedProfileContext
    from hermes_db.domains.sessions.postgres.context import SessionContext
    from hermes_db.domains.sessions.postgres.catalog import SessionCatalog
    from hermes_db.domains.sessions.postgres.messages import SessionMessages
    from hermes_db.domains.sessions.postgres.history import SessionHistory
    from hermes_db.domains.sessions.postgres.lifecycle import SessionLifecycle
    from hermes_db.domains.sessions.postgres.usage import SessionUsage
    from hermes_db.integration.transfer.session_store import SessionTransfer
    from hermes_db.domains.sessions.postgres.support.usage_writer import UsageWriter
    from hermes_db.domains.sessions.postgres.store import PostgresSessionStore

    profile = OwnedProfileContext(scope)
    context = SessionContext(transactions, scope, own_profile=profile_name_for_home(scope.profile_home), profile=profile)
    usage = SessionUsage(context)
    context.usage_writer = UsageWriter(usage.update_token_counts, profile)
    catalog = SessionCatalog(context, flush_for_read=usage.flush_for_read, flush_token_counts=usage.flush_token_counts)
    messages = SessionMessages(context, get_session=catalog.get_session)
    history = SessionHistory(context, get_active_message_ids=messages.get_active_message_ids, get_messages_as_conversation=messages.get_messages_as_conversation, list_sessions_rich=catalog.list_sessions_rich, rewind_to_message=messages.rewind_to_message)
    lifecycle = SessionLifecycle(context, flush_for_read=usage.flush_for_read)
    transfer = SessionTransfer(context, _after_session_delete=lifecycle._after_session_delete, flush_for_read=usage.flush_for_read, flush_token_counts=usage.flush_token_counts)
    return PostgresSessionStore(context, catalog, messages, history, lifecycle, usage, transfer)
