"""Public session facade with explicit component delegation; resource identity belongs to its shared context."""
from __future__ import annotations
from typing import Any, Optional
from hermes_db.domains.sessions.rewind import RewindPlan, RewindOutcome
from hermes_db.domains.sessions.postgres.catalog import SessionCatalog
from hermes_db.domains.sessions.postgres.lifecycle import SessionLifecycle
from hermes_db.domains.sessions.postgres.history import SessionHistory

class PostgresSessionStore:

    def __init__(self, context, catalog, messages, history, lifecycle, usage, transfer):
        self._context = context
        self._catalog = catalog
        self._messages = messages
        self._history = history
        self._lifecycle = lifecycle
        self._usage = usage
        self._transfer = transfer

    @property
    def _transactions(self):
        return self._context.transactions

    @property
    def _scope(self):
        return self._context.scope

    @property
    def scope(self):
        return self._context.scope

    @property
    def _own_profile(self):
        return self._context.own_profile

    @property
    def _profile(self):
        return self._context.profile

    @property
    def _closed(self):
        return self._context.closed

    @property
    def _usage_writer(self):
        return self._context.usage_writer

    def _read(self):
        return self._context.read()

    def _write(self):
        return self._context.write()

    def _assert_open(self):
        return self._context.assert_open()

    def close(self):
        return self._context.close()

    def backfill_repo_roots(self, cwd_to_root):
        return self._catalog.backfill_repo_roots(cwd_to_root)

    def update_system_prompt(self, session_id, system_prompt):
        return self._catalog.update_system_prompt(session_id, system_prompt)

    def update_session_tool_names(self, session_id, pin):
        return self._catalog.update_session_tool_names(session_id, pin)

    def patch_session_model_config(self, session_id, patch):
        return self._catalog.patch_session_model_config(session_id, patch)

    def get_session_model_config_value(self, session_id, key, default=None):
        return self._catalog.get_session_model_config_value(session_id, key, default)

    def update_session_model(self, session_id, model, provider=None, *, base_url=None, api_mode=None):
        return self._catalog.update_session_model(session_id, model, provider, base_url=base_url, api_mode=api_mode)

    def update_session_meta(self, session_id, model_config_json, model=None):
        return self._catalog.update_session_meta(session_id, model_config_json, model)

    def update_session_runtime_lock(self, session_id, *, model=None, provider=None, model_options=None, route_source=None, confirmed=False):
        return self._catalog.update_session_runtime_lock(session_id, model=model, provider=provider, model_options=model_options, route_source=route_source, confirmed=confirmed)

    def update_conversation_model_config_value(self, session_id, key, update):
        return self._catalog.update_conversation_model_config_value(session_id, key, update)

    def session_ids_with_model_config_key(self, key):
        return self._catalog.session_ids_with_model_config_key(key)

    def set_session_yolo(self, session_id, enabled):
        return self._catalog.set_session_yolo(session_id, enabled)

    @staticmethod
    def session_yolo_enabled(session_meta):
        return SessionCatalog.session_yolo_enabled(session_meta)

    def set_expiry_finalized(self, session_id, finalized=True):
        return self._catalog.set_expiry_finalized(session_id, finalized)

    def set_session_archived(self, session_id, archived, *, notify=True):
        return self._catalog.set_session_archived(session_id, archived, notify=notify)

    def set_session_hidden(self, session_id, hidden):
        return self._catalog.set_session_hidden(session_id, hidden)

    def set_session_pinned(self, session_id, pinned):
        return self._catalog.set_session_pinned(session_id, pinned)

    def set_session_read(self, session_id, read=True):
        return self._catalog.set_session_read(session_id, read)

    @staticmethod
    def session_unread(session_row):
        return SessionCatalog.session_unread(session_row)

    def update_session_cwd(self, session_id, cwd, git_branch=None, git_repo_root=None, replace_git_meta=False):
        return self._catalog.update_session_cwd(session_id, cwd, git_branch, git_repo_root, replace_git_meta)

    def publish_session_git_metadata(self, session_id, cwd, generation, git_branch=None, git_repo_root=None):
        return self._catalog.publish_session_git_metadata(session_id, cwd, generation, git_branch, git_repo_root)

    def touch_session_activity(self, session_id, ts=None, *, description=None, provenance=None):
        return self._catalog.touch_session_activity(session_id, ts, description=description, provenance=provenance)

    def clear_session_activity_labels(self, session_id):
        return self._catalog.clear_session_activity_labels(session_id)

    def retire_undrained_queue_rows(self, session_id):
        return self._catalog.retire_undrained_queue_rows(session_id)

    def promote_to_session_reset(self, session_id, reason='session_reset'):
        return self._catalog.promote_to_session_reset(session_id, reason)

    def unarchive_recoverable_session(self, session_id):
        return self._catalog.unarchive_recoverable_session(session_id)

    def declared_scope_identity(self, session_id):
        return self._catalog.declared_scope_identity(session_id)

    def get_session_rich_row(self, session_id, compact_rows=False):
        return self._catalog.get_session_rich_row(session_id, compact_rows)

    def get_session_list_row(self, session_id):
        return self._catalog.get_session_list_row(session_id)

    def resolve_session_id(self, session_id_or_prefix):
        return self._catalog.resolve_session_id(session_id_or_prefix)

    def find_session_by_origin(self, *, platform, chat_id, thread_id=None, user_id=None):
        return self._catalog.find_session_by_origin(platform=platform, chat_id=chat_id, thread_id=thread_id, user_id=user_id)

    def list_sessions_rich(self, source=None, sources=None, exclude_sources=None, cwd_prefix=None, limit=20, offset=0, include_children=False, min_message_count=0, project_compression_tips=True, order_by_last_active=False, include_archived=False, archived_only=False, id_query=None, search_query=None, compact_rows=False, include_pinned=False, session_key=None, include_hidden=False, include_subagents=False, local_created_sources=None, workspace_key=None):
        return self._catalog.list_sessions_rich(source, sources, exclude_sources, cwd_prefix, limit, offset, include_children, min_message_count, project_compression_tips, order_by_last_active, include_archived, archived_only, id_query, search_query, compact_rows, include_pinned, session_key, include_hidden, include_subagents, local_created_sources, workspace_key)

    def session_count(self, source=None, sources=None, cwd_prefix=None, min_message_count=0, include_archived=False, archived_only=False, exclude_children=False, exclude_sources=None, include_subagents=False, local_created_sources=None):
        return self._catalog.session_count(source, sources, cwd_prefix, min_message_count, include_archived, archived_only, exclude_children, exclude_sources, include_subagents, local_created_sources)

    def session_count_ge(self, n=1):
        return self._catalog.session_count_ge(n)

    def session_count_by_source(self, *, include_archived=False, archived_only=False, exclude_children=False):
        return self._catalog.session_count_by_source(include_archived=include_archived, archived_only=archived_only, exclude_children=exclude_children)

    def search_sessions(self, source=None, limit=20, offset=0, workspace_key=None, local_created_sources=None, skip_launch_stubs=False):
        return self._catalog.search_sessions(source, limit, offset, workspace_key, local_created_sources, skip_launch_stubs)

    def list_recent_sessions_bounded(self, *, limit=20, exclude_sources=None, timeout_seconds=3.0, candidate_limit=None, lineage_limit=None):
        return self._catalog.list_recent_sessions_bounded(limit=limit, exclude_sources=exclude_sources, timeout_seconds=timeout_seconds, candidate_limit=candidate_limit, lineage_limit=lineage_limit)

    def session_lifecycle_statuses(self, session_ids):
        return self._catalog.session_lifecycle_statuses(session_ids)

    def count_empty_sessions(self):
        return self._catalog.count_empty_sessions()

    @staticmethod
    def sanitize_title(value):
        return SessionCatalog.sanitize_title(value)

    def set_session_title(self, session_id, title):
        return self._catalog.set_session_title(session_id, title)

    def set_auto_title(self, session_id, title, *, source):
        return self._catalog.set_auto_title(session_id, title, source=source)

    def displace_bot_chat(self, session_id, title):
        return self._catalog.displace_bot_chat(session_id, title)

    def get_session_title(self, session_id):
        return self._catalog.get_session_title(session_id)

    def get_session_title_source(self, session_id):
        return self._catalog.get_session_title_source(session_id)

    def set_session_title_source(self, session_id, source):
        return self._catalog.set_session_title_source(session_id, source)

    def get_session_by_title(self, title):
        return self._catalog.get_session_by_title(title)

    def resolve_session_by_title(self, title):
        return self._catalog.resolve_session_by_title(title)

    def get_next_title_in_lineage(self, base_title):
        return self._catalog.get_next_title_in_lineage(base_title)

    def apply_telegram_topic_migration(self):
        return self._catalog.apply_telegram_topic_migration()

    def enable_telegram_topic_mode(self, *, chat_id, user_id, profile_name='default', has_topics_enabled=None, allows_users_to_create_topics=None):
        return self._catalog.enable_telegram_topic_mode(chat_id=chat_id, user_id=user_id, profile_name=profile_name, has_topics_enabled=has_topics_enabled, allows_users_to_create_topics=allows_users_to_create_topics)

    def disable_telegram_topic_mode(self, *, chat_id, profile_name='default', clear_bindings=True):
        return self._catalog.disable_telegram_topic_mode(chat_id=chat_id, profile_name=profile_name, clear_bindings=clear_bindings)

    def is_telegram_topic_mode_enabled(self, *, chat_id, user_id, profile_name='default'):
        return self._catalog.is_telegram_topic_mode_enabled(chat_id=chat_id, user_id=user_id, profile_name=profile_name)

    def get_telegram_topic_binding(self, *, chat_id, thread_id, profile_name='default'):
        return self._catalog.get_telegram_topic_binding(chat_id=chat_id, thread_id=thread_id, profile_name=profile_name)

    def list_telegram_topic_bindings_for_chat(self, *, chat_id, profile_name='default'):
        return self._catalog.list_telegram_topic_bindings_for_chat(chat_id=chat_id, profile_name=profile_name)

    def get_telegram_topic_binding_by_session(self, *, session_id):
        return self._catalog.get_telegram_topic_binding_by_session(session_id=session_id)

    def is_telegram_session_linked_to_topic(self, *, session_id):
        return self._catalog.is_telegram_session_linked_to_topic(session_id=session_id)

    def bind_telegram_topic(self, *, chat_id, thread_id, user_id, session_key, session_id, managed_mode='auto', profile_name='default', expected_session_id=None):
        return self._catalog.bind_telegram_topic(chat_id=chat_id, thread_id=thread_id, user_id=user_id, session_key=session_key, session_id=session_id, managed_mode=managed_mode, profile_name=profile_name, expected_session_id=expected_session_id)

    def delete_telegram_topic_binding(self, *, chat_id, thread_id, profile_name='default'):
        return self._catalog.delete_telegram_topic_binding(chat_id=chat_id, thread_id=thread_id, profile_name=profile_name)

    def list_unlinked_telegram_sessions_for_user(self, *, chat_id, user_id, profile_name='default', limit=10):
        return self._catalog.list_unlinked_telegram_sessions_for_user(chat_id=chat_id, user_id=user_id, profile_name=profile_name, limit=limit)

    def sessions_in_workspace(self, session_ids, workspace):
        return self._catalog.sessions_in_workspace(session_ids, workspace)

    def picker_session_facts(self, root_ids, unlisted_ids, segment_ids):
        return self._catalog.picker_session_facts(root_ids, unlisted_ids, segment_ids)

    def session_current_segments(self, session_ids):
        return self._catalog.session_current_segments(session_ids)

    def subagent_session_ids(self, subagent_id, marker_key):
        return self._catalog.subagent_session_ids(subagent_id, marker_key)

    def request_prompt_refresh(self, session_id=None):
        return self._catalog.request_prompt_refresh(session_id)

    def prompt_refresh_epoch(self, session_id):
        return self._catalog.prompt_refresh_epoch(session_id)

    def count_sessions_with_stored_prompt(self):
        return self._catalog.count_sessions_with_stored_prompt()

    def append_message(self, session_id, role, content=None, tool_name=None, tool_calls=None, tool_call_id=None, token_count=None, finish_reason=None, reasoning=None, reasoning_content=None, reasoning_details=None, codex_reasoning_items=None, codex_message_items=None, platform_message_id=None, observed=False, effect_disposition=None, _compressed_summary=False, timestamp=None, api_content=None, display_kind=None, display_metadata=None, compression_lock_holder=None, turn_lease_holder=None, turn_lease_ttl_seconds=300.0, message_uid=None):
        return self._messages.append_message(session_id, role, content, tool_name, tool_calls, tool_call_id, token_count, finish_reason, reasoning, reasoning_content, reasoning_details, codex_reasoning_items, codex_message_items, platform_message_id, observed, effect_disposition, _compressed_summary, timestamp, api_content, display_kind, display_metadata, compression_lock_holder, turn_lease_holder, turn_lease_ttl_seconds, message_uid)

    def append_messages_batch(self, session_id, messages, compression_lock_holder=None, turn_lease_holder=None, chunk_rows=None, turn_lease_ttl_seconds=300.0):
        return self._messages.append_messages_batch(session_id, messages, compression_lock_holder, turn_lease_holder, chunk_rows, turn_lease_ttl_seconds)

    def replace_messages(self, session_id, messages, active_only=False, archive_dropped=False, reject_active_turn_lease=False):
        return self._messages.replace_messages(session_id, messages, active_only, archive_dropped, reject_active_turn_lease)

    def replace_messages_in_transaction(self, conn, session_id, messages, *, active_only=False, archive_dropped=False, reject_active_turn_lease=False, expected_active_ids=None):
        return self._messages.replace_messages_in_transaction(conn, session_id, messages, active_only=active_only, archive_dropped=archive_dropped, reject_active_turn_lease=reject_active_turn_lease, expected_active_ids=expected_active_ids)

    def rewind_to_message(self, session_id, target_message_id, *, preserve_compaction_handoff=False, expected_active_ids=None, expected_target_content=None):
        return self._messages.rewind_to_message(session_id, target_message_id, preserve_compaction_handoff=preserve_compaction_handoff, expected_active_ids=expected_active_ids, expected_target_content=expected_target_content)

    def transcript_cursor_state(self, session_id, through_id, lineage_ids=None):
        return self._messages.transcript_cursor_state(session_id, through_id, lineage_ids)

    def transcript_lineage_ids(self, session_id):
        return self._messages.transcript_lineage_ids(session_id)

    def get_messages(self, session_id, include_inactive=False, include_compacted=False, limit=None, offset=0, latest=False, after_id=None, include_ancestors=False):
        return self._messages.get_messages(session_id, include_inactive, include_compacted, limit, offset, latest, after_id, include_ancestors)

    def get_messages_as_conversation(self, session_id, include_ancestors=False, include_inactive=False, repair_alternation=False, include_row_ids=False, include_compacted=False):
        return self._messages.get_messages_as_conversation(session_id, include_ancestors, include_inactive, repair_alternation, include_row_ids, include_compacted)

    def get_resume_conversations(self, session_id):
        return self._messages.get_resume_conversations(session_id)

    def get_active_message_ids(self, session_id):
        return self._messages.get_active_message_ids(session_id)

    def get_active_message_watermark(self, session_id):
        return self._messages.get_active_message_watermark(session_id)

    def conversation_revision(self, session_id, include_ancestors=False):
        return self._messages.conversation_revision(session_id, include_ancestors)

    def message_count(self, session_id=None):
        return self._messages.message_count(session_id)

    def has_archived_messages(self, session_id):
        return self._messages.has_archived_messages(session_id)

    def get_resume_message_count(self, session_id, *, tip_only=False):
        return self._messages.get_resume_message_count(session_id, tip_only=tip_only)

    def assert_resume_safe(self, session_id, max_messages=None, *, tip_only=False):
        return self._messages.assert_resume_safe(session_id, max_messages, tip_only=tip_only)

    def get_ancestor_display_prefix(self, session_id):
        return self._messages.get_ancestor_display_prefix(session_id)

    def get_conversation_root(self, session_id):
        return self._messages.get_conversation_root(session_id)

    def is_explicit_fork_child(self, session_id):
        return self._messages.is_explicit_fork_child(session_id)

    def latest_message_row_id(self, session_id, *, role='user', offset=0, require_text=True):
        return self._messages.latest_message_row_id(session_id, role=role, offset=offset, require_text=require_text)

    def latest_conversation_role(self, session_id):
        return self._messages.latest_conversation_role(session_id)

    def get_message_role(self, session_id, row_id):
        return self._messages.get_message_role(session_id, row_id)

    def get_messages_around(self, session_id, around_message_id, window=5):
        return self._messages.get_messages_around(session_id, around_message_id, window)

    def has_platform_message_id(self, session_id, platform_message_id):
        return self._messages.has_platform_message_id(session_id, platform_message_id)

    def has_gateway_input_owner(self, session_id, owner):
        return self._messages.has_gateway_input_owner(session_id, owner)

    def latest_conversation_boundary(self, session_key, source):
        return self._messages.latest_conversation_boundary(session_key, source)

    def find_pr_url_messages(self, session_ids):
        return self._messages.find_pr_url_messages(session_ids)

    def display_message_count(self, session_id):
        return self._messages.display_message_count(session_id)

    def resolve_resume_session_id(self, session_id):
        return self._messages.resolve_resume_session_id(session_id)

    def set_message_api_content(self, session_id, row_id, content, api_content):
        return self._messages.set_message_api_content(session_id, row_id, content, api_content)

    def _backfill_api_content(self, conn, session_id, row_id, content, api_content):
        return self._messages._backfill_api_content(conn, session_id, row_id, content, api_content)

    def set_latest_user_api_content(self, session_id, content, api_content):
        return self._messages.set_latest_user_api_content(session_id, content, api_content)

    def set_user_message_content(self, session_id, row_id, content, display_metadata=None):
        return self._messages.set_user_message_content(session_id, row_id, content, display_metadata)

    def deactivate_message(self, session_id, row_id):
        return self._messages.deactivate_message(session_id, row_id)

    def deactivate_messages_by_display_kind(self, session_id, display_kind):
        return self._messages.deactivate_messages_by_display_kind(session_id, display_kind)

    def resolve_active_row_id(self, session_id, row_id):
        return self._messages.resolve_active_row_id(session_id, row_id)

    def clear_messages(self, session_id):
        return self._messages.clear_messages(session_id)

    def set_latest_matching_message_display_kind(self, session_id, *, role, content, display_kind, display_metadata=None):
        return self._messages.set_latest_matching_message_display_kind(session_id, role=role, content=content, display_kind=display_kind, display_metadata=display_metadata)

    def set_message_reaction(self, session_id, message_row_id, emoji, *, author='user'):
        return self._messages.set_message_reaction(session_id, message_row_id, emoji, author=author)

    def get_message_reactions(self, session_id, message_row_id):
        return self._messages.get_message_reactions(session_id, message_row_id)

    def take_unseen_reactions(self, session_id, *, author='user'):
        return self._messages.take_unseen_reactions(session_id, author=author)

    def append_delegation_delivery(self, session_id, content, metadata):
        return self._messages.append_delegation_delivery(session_id, content, metadata)

    def append_completion_note(self, session_id, admission_id, content, display_kind, metadata):
        return self._messages.append_completion_note(session_id, admission_id, content, display_kind, metadata)

    def _append_result(self, session_id, content, display_kind, metadata, identity):
        return self._messages._append_result(session_id, content, display_kind, metadata, identity)

    def get_latest_todo_result(self, session_id, *, max_chars=None):
        return self._messages.get_latest_todo_result(session_id, max_chars=max_chars)

    def publish_compression_child(self, *, parent_session_id, child_session_id, source, messages, model=None, model_config=None, system_prompt=None, cwd=None, profile_name=None, compression_lock_holder=None, require_compression_lease=True, require_lease_refresh=False, lease_ttl_seconds=300.0, watermark=None, watermark_ceiling=None):
        return self._history.publish_compression_child(parent_session_id=parent_session_id, child_session_id=child_session_id, source=source, messages=messages, model=model, model_config=model_config, system_prompt=system_prompt, cwd=cwd, profile_name=profile_name, compression_lock_holder=compression_lock_holder, require_compression_lease=require_compression_lease, require_lease_refresh=require_lease_refresh, lease_ttl_seconds=lease_ttl_seconds, watermark=watermark, watermark_ceiling=watermark_ceiling)

    def get_compression_chain(self, session_id):
        return self._history.get_compression_chain(session_id)

    def get_compression_tip(self, session_id):
        return self._history.get_compression_tip(session_id)

    def archive_and_compact(self, session_id, compacted_messages, model_config_patch=None, watermark=None, lock_holder=None, tail_count=0, carried_messages=None, covered_ids=None, unresolved_held=None, held_for_cas=None):
        return self._history.archive_and_compact(session_id, compacted_messages, model_config_patch, watermark, lock_holder, tail_count, carried_messages, covered_ids, unresolved_held, held_for_cas)

    def rewritten_held_row_ids(self, session_id, held):
        return self._history.rewritten_held_row_ids(session_id, held)

    def held_row_mismatches(self, conn, session_id, held):
        return self._history.held_row_mismatches(conn, session_id, held)

    def get_compression_failure_cooldown_row(self, session_id):
        return self._history.get_compression_failure_cooldown_row(session_id)

    def get_compression_failure_cooldown(self, session_id):
        return self._history.get_compression_failure_cooldown(session_id)

    def record_compression_failure_cooldown(self, session_id, cooldown_until, error=None):
        return self._history.record_compression_failure_cooldown(session_id, cooldown_until, error)

    def restore_compression_failure_cooldown_row(self, session_id, snapshot):
        return self._history.restore_compression_failure_cooldown_row(session_id, snapshot)

    def clear_compression_failure_cooldown(self, session_id):
        return self._history.clear_compression_failure_cooldown(session_id)

    def _compression_number(self, session_id, column, cast=int):
        return self._history._compression_number(session_id, column, cast)

    def _set_compression_number(self, session_id, column, value):
        return self._history._set_compression_number(session_id, column, value)

    def get_compression_fallback_streak(self, session_id):
        return self._history.get_compression_fallback_streak(session_id)

    def set_compression_fallback_streak(self, session_id, streak):
        return self._history.set_compression_fallback_streak(session_id, streak)

    def get_compression_ineffective_count(self, session_id):
        return self._history.get_compression_ineffective_count(session_id)

    def set_compression_ineffective_count(self, session_id, count):
        return self._history.set_compression_ineffective_count(session_id, count)

    def get_compression_overload_streak(self, session_id):
        return self._history.get_compression_overload_streak(session_id)

    def set_compression_overload_streak(self, session_id, streak):
        return self._history.set_compression_overload_streak(session_id, streak)

    def increment_compression_overload_streak(self, session_id):
        return self._history.increment_compression_overload_streak(session_id)

    def get_compression_recovery_deadline(self, session_id):
        return self._history.get_compression_recovery_deadline(session_id)

    def set_compression_recovery_deadline(self, session_id, deadline):
        return self._history.set_compression_recovery_deadline(session_id, deadline)

    def reopen_if_explicitly_closed(self, session_id, *, provenance, patience_s=None):
        return self._history.reopen_if_explicitly_closed(session_id, provenance=provenance, patience_s=patience_s)

    def reopen_orphaned_compression_session(self, session_id):
        return self._history.reopen_orphaned_compression_session(session_id)

    def find_live_compression_child(self, parent_session_id):
        return self._history.find_live_compression_child(parent_session_id)

    def finalize_orphaned_compression_sessions(self):
        return self._history.finalize_orphaned_compression_sessions()

    def get_compression_lineage(self, session_id):
        return self._history.get_compression_lineage(session_id)

    def retain_refused_turn_for_display(self, session_id, *, notice, boundary_row_id=None):
        return self._history.retain_refused_turn_for_display(session_id, notice=notice, boundary_row_id=boundary_row_id)

    def rewrite_pruned_rows(self, session_id, changes, *, model_config_patch=None, turn_lease_holder=None, turn_lease_ttl_seconds=300):
        return self._history.rewrite_pruned_rows(session_id, changes, model_config_patch=model_config_patch, turn_lease_holder=turn_lease_holder, turn_lease_ttl_seconds=turn_lease_ttl_seconds)

    def rewind_user_turn(self, session_id: str, user_ordinal: int, *, warm_history: Optional[list[dict[str, Any]]]=None, require_retryable: bool=False, require_composite: bool=False, adopt_row_ids: bool=False) -> RewindOutcome:
        return self._history.rewind_user_turn(session_id, user_ordinal, warm_history=warm_history, require_retryable=require_retryable, require_composite=require_composite, adopt_row_ids=adopt_row_ids)

    def plan_user_turn_rewind(self, session_id: str, user_ordinal: int, *, warm_history: Optional[list[dict[str, Any]]]=None, require_retryable: bool=False, require_composite: bool=False) -> RewindPlan:
        return self._history.plan_user_turn_rewind(session_id, user_ordinal, warm_history=warm_history, require_retryable=require_retryable, require_composite=require_composite)

    def _resume_lineage_ids(self, session_id):
        return self._history._resume_lineage_ids(session_id)

    def _rows_to_conversation(self, rows, **kwargs):
        return self._history._rows_to_conversation(rows, **kwargs)

    def _dedupe_display_generations(self, rows, **kwargs):
        return self._history._dedupe_display_generations(rows, **kwargs)

    def _fetch_conversation_rows(self, session_ids, extra_where='', *, with_session_id=False, with_compacted=False):
        return self._history._fetch_conversation_rows(session_ids, extra_where, with_session_id=with_session_id, with_compacted=with_compacted)

    def _ensure_display_order(self, session_id):
        return self._history._ensure_display_order(session_id)

    def transcript_display_index_complete(self, segment):
        return self._history.transcript_display_index_complete(segment)

    def transcript_segment_page(self, segment, *, latest, after, count, inclusive=False):
        return self._history.transcript_segment_page(segment, latest=latest, after=after, count=count, inclusive=inclusive)

    def transcript_tool_calls_before(self, segment_ids, before_id, limit=16):
        return self._history.transcript_tool_calls_before(segment_ids, before_id, limit)

    def transcript_handoff_rows(self, shown_ids, segment_ids):
        return self._history.transcript_handoff_rows(shown_ids, segment_ids)

    def transcript_handoffs_shown_before(self, segment, before, handoffs):
        return self._history.transcript_handoffs_shown_before(segment, before, handoffs)

    @staticmethod
    def _is_explicit_fork_child_row(row, *, include_reset=False):
        return SessionHistory._is_explicit_fork_child_row(row, include_reset=include_reset)

    def get_tool_rotation_root(self, session_id):
        return self._history.get_tool_rotation_root(session_id)

    def delegate_descendant_ids(self, session_id):
        return self._history.delegate_descendant_ids(session_id)

    def get_anchored_view(self, session_id, around_message_id, window=5, bookend=3, keep_roles=('user', 'assistant')):
        return self._history.get_anchored_view(session_id, around_message_id, window, bookend, keep_roles)

    def list_recent_user_messages(self, session_id, limit=20, include_inactive=False):
        return self._history.list_recent_user_messages(session_id, limit, include_inactive)

    def search_messages(self, query, source_filter=None, exclude_sources=None, role_filter=None, limit=20, offset=0, sort=None, include_inactive=False, fields=None, after_ts=None, before_ts=None):
        return self._history.search_messages(query, source_filter, exclude_sources, role_filter, limit, offset, sort, include_inactive, fields, after_ts, before_ts)

    def search_sessions_by_id(self, query: str, limit: int=20, include_archived: bool=True, source: str | None=None, sources: list[str] | None=None, exclude_sources: list[str] | None=None) -> list[dict[str, Any]]:
        return self._history.search_sessions_by_id(query, limit, include_archived, source, sources, exclude_sources)

    def _change_lease(self, session_id, holder, action, *, turn=False, ttl_seconds=300, patience_s=None):
        return self._lifecycle._change_lease(session_id, holder, action, turn=turn, ttl_seconds=ttl_seconds, patience_s=patience_s)

    def try_acquire_compression_lock(self, session_id, holder, ttl_seconds=300.0):
        return self._lifecycle.try_acquire_compression_lock(session_id, holder, ttl_seconds)

    def refresh_compression_lock(self, session_id, holder, ttl_seconds=300.0):
        return self._lifecycle.refresh_compression_lock(session_id, holder, ttl_seconds)

    def release_compression_lock(self, session_id, holder):
        return self._lifecycle.release_compression_lock(session_id, holder)

    def get_compression_lock_holder(self, session_id):
        return self._lifecycle.get_compression_lock_holder(session_id)

    def try_acquire_session_turn_lease(self, session_id, holder, *, ttl_seconds=300.0, patience_s=None):
        return self._lifecycle.try_acquire_session_turn_lease(session_id, holder, ttl_seconds=ttl_seconds, patience_s=patience_s)

    def refresh_session_turn_lease(self, session_id, holder, *, ttl_seconds=300.0, patience_s=None):
        return self._lifecycle.refresh_session_turn_lease(session_id, holder, ttl_seconds=ttl_seconds, patience_s=patience_s)

    def release_session_turn_lease(self, session_id, holder):
        return self._lifecycle.release_session_turn_lease(session_id, holder)

    def session_turn_lease_expires_at(self, session_id, holder):
        return self._lifecycle.session_turn_lease_expires_at(session_id, holder)

    def _session_turn_lease_key(self, session_id):
        return self._lifecycle._session_turn_lease_key(session_id)

    def _lease_callback(self, callback, *args):
        return self._lifecycle._lease_callback(callback, *args)

    def acquire_session_turn_lease(self, session_id, holder, *, ttl_seconds=300.0, wait_seconds=1800.0, poll_interval_seconds=1.0, on_wait=None, wait_notice_interval_seconds=15.0, should_abort=None, acquire_patience_s=0.5, on_contended=None):
        return self._lifecycle.acquire_session_turn_lease(session_id, holder, ttl_seconds=ttl_seconds, wait_seconds=wait_seconds, poll_interval_seconds=poll_interval_seconds, on_wait=on_wait, wait_notice_interval_seconds=wait_notice_interval_seconds, should_abort=should_abort, acquire_patience_s=acquire_patience_s, on_contended=on_contended)

    def delete_session(self, session_id, sessions_dir=None, expected_delete_ids=None, expected_display_messages=None, exclude_active_write_guards=False, include_compression_chain=False):
        return self._lifecycle.delete_session(session_id, sessions_dir, expected_delete_ids, expected_display_messages, exclude_active_write_guards, include_compression_chain)

    def delete_sessions(self, session_ids, sessions_dir=None, exclude_active_write_guards=False, skipped_ids=None, include_compression_chain=False):
        return self._lifecycle.delete_sessions(session_ids, sessions_dir, exclude_active_write_guards, skipped_ids, include_compression_chain)

    def _after_session_delete(self, targets, *, primary=None, reason='delete', sessions_dir=None):
        return self._lifecycle._after_session_delete(targets, primary=primary, reason=reason, sessions_dir=sessions_dir)

    def collect_retired_media(self):
        return self._lifecycle.collect_retired_media()

    def _export_limit(self, maximum):
        return self._lifecycle._export_limit(maximum)

    def assert_export_safe(self, session_id, max_messages=None):
        return self._lifecycle.assert_export_safe(session_id, max_messages)

    def assert_exports_safe(self, session_ids, max_messages=None):
        return self._lifecycle.assert_exports_safe(session_ids, max_messages)

    def get_session_delete_targets(self, session_id):
        return self._lifecycle.get_session_delete_targets(session_id)

    def session_is_empty(self, session_id):
        return self._lifecycle.session_is_empty(session_id)

    def prune_empty_ghost_sessions(self, sessions_dir=None):
        return self._lifecycle.prune_empty_ghost_sessions(sessions_dir)

    def delete_empty_sessions(self, sessions_dir=None):
        return self._lifecycle.delete_empty_sessions(sessions_dir)

    def delete_session_if_empty(self, session_id, sessions_dir=None):
        return self._lifecycle.delete_session_if_empty(session_id, sessions_dir)

    def discard_unadmitted_session(self, session_id):
        return self._lifecycle.discard_unadmitted_session(session_id)

    def prune_never_active_keyed_sessions(self, *, older_than_days, sessions_dir=None, deleted_ids=None):
        return self._lifecycle.prune_never_active_keyed_sessions(older_than_days=older_than_days, sessions_dir=sessions_dir, deleted_ids=deleted_ids)

    def prune_retired_tombstones(self, older_than=604800):
        return self._lifecycle.prune_retired_tombstones(older_than)

    def retired_session(self, session_id):
        return self._lifecycle.retired_session(session_id)

    def create_conflict(self, session_id):
        return self._lifecycle.create_conflict(session_id)

    def has_mutation_receipt(self, principal_id, session_id, request_id):
        return self._lifecycle.has_mutation_receipt(principal_id, session_id, request_id)

    def first_generation(self, derive, *, pinned=None, spent=None):
        return self._lifecycle.first_generation(derive, pinned=pinned, spent=spent)

    def keep_passed_fences(self, derive, session_id):
        return self._lifecycle.keep_passed_fences(derive, session_id)

    def list_prune_candidates(self, older_than_days=None, source=None, *, whole_lineages=False, **filters):
        return self._lifecycle.list_prune_candidates(older_than_days, source, whole_lineages=whole_lineages, **filters)

    def count_prune_matches(self, older_than_days=None, source=None, *, pinned_only=False, **filters):
        return self._lifecycle.count_prune_matches(older_than_days, source, pinned_only=pinned_only, **filters)

    def count_open_prune_matches(self, older_than_days=None, source=None, **filters):
        return self._lifecycle.count_open_prune_matches(older_than_days, source, **filters)

    def archive_sessions(self, older_than_days=None, source=None, **filters):
        return self._lifecycle.archive_sessions(older_than_days, source, **filters)

    def _emit_archives(self, events):
        return self._lifecycle._emit_archives(events)

    def prune_sessions(self, older_than_days=90, source=None, sessions_dir=None, exclude_active_write_guards=False, deleted_ids=None, **filters):
        return self._lifecycle.prune_sessions(older_than_days, source, sessions_dir, exclude_active_write_guards, deleted_ids, **filters)

    def archive_stale_sessions(self, idle_days, *, exclude_pinned=True):
        return self._lifecycle.archive_stale_sessions(idle_days, exclude_pinned=exclude_pinned)

    def maybe_auto_archive(self, idle_days=3, min_interval_hours=24, exclude_pinned=True):
        return self._lifecycle.maybe_auto_archive(idle_days, min_interval_hours, exclude_pinned)

    def sweep_orphaned_sessions(self, **options):
        return self._lifecycle.sweep_orphaned_sessions(**options)

    def maybe_auto_prune_and_vacuum(self, retention_days=90, min_interval_hours=24, vacuum=True, sessions_dir=None, min_vacuum_interval_days=30, min_vacuum_freelist_ratio=0.25):
        return self._lifecycle.maybe_auto_prune_and_vacuum(retention_days, min_interval_hours, vacuum, sessions_dir, min_vacuum_interval_days, min_vacuum_freelist_ratio)

    def register_backend_heartbeat(self, *, backend_id, pid, started_at, last_heartbeat=None, profile='', host=''):
        return self._lifecycle.register_backend_heartbeat(backend_id=backend_id, pid=pid, started_at=started_at, last_heartbeat=last_heartbeat, profile=profile, host=host)

    def clear_backend_heartbeat(self, backend_id):
        return self._lifecycle.clear_backend_heartbeat(backend_id)

    def prune_stale_heartbeats(self, *, max_age_seconds):
        return self._lifecycle.prune_stale_heartbeats(max_age_seconds=max_age_seconds)

    def list_backend_heartbeats(self):
        return self._lifecycle.list_backend_heartbeats()

    def increment_hygiene_failure_streak(self, session_key):
        return self._lifecycle.increment_hygiene_failure_streak(session_key)

    def reset_hygiene_failure_streak(self, session_key):
        return self._lifecycle.reset_hygiene_failure_streak(session_key)

    def _handoff_update(self, session_id, values, *conditions):
        return self._lifecycle._handoff_update(session_id, values, *conditions)

    def request_handoff(self, session_id, platform):
        return self._lifecycle.request_handoff(session_id, platform)

    def get_handoff_state(self, session_id):
        return self._lifecycle.get_handoff_state(session_id)

    def list_pending_handoffs(self):
        return self._lifecycle.list_pending_handoffs()

    def claim_handoff(self, session_id):
        return self._lifecycle.claim_handoff(session_id)

    def has_pending_handoffs(self):
        return self._lifecycle.has_pending_handoffs()

    def complete_handoff(self, session_id):
        return self._lifecycle.complete_handoff(session_id)

    def fail_handoff(self, session_id, error, *, only_states=None):
        return self._lifecycle.fail_handoff(session_id, error, only_states=only_states)

    def reclaim_stale_running_handoffs(self, error):
        return self._lifecycle.reclaim_stale_running_handoffs(error)

    @staticmethod
    def session_gateway_runtime(session_meta: Optional[dict[str, Any]]) -> dict[str, Any]:
        return SessionLifecycle.session_gateway_runtime(session_meta)

    def purge_profile_state(self, profile):
        return self._lifecycle.purge_profile_state(profile)

    def rekey_profile_state(self, old_name, new_name):
        return self._lifecycle.rekey_profile_state(old_name, new_name)

    def save_gateway_routing_entry(self, session_key, entry_json, *, scope=''):
        return self._lifecycle.save_gateway_routing_entry(session_key, entry_json, scope=scope)

    def replace_gateway_routing_entries(self, entries, *, scope=''):
        return self._lifecycle.replace_gateway_routing_entries(entries, scope=scope)

    def load_gateway_routing_entries(self, *, scope=''):
        return self._lifecycle.load_gateway_routing_entries(scope=scope)

    def gateway_routing_entry_for_session(self, session_id):
        return self._lifecycle.gateway_routing_entry_for_session(session_id)

    def retire_gateway_routes(self, session_ids, *, namespace, expiring=()):
        return self._lifecycle.retire_gateway_routes(session_ids, namespace=namespace, expiring=expiring)

    def record_gateway_session_peer(self, session_id, *, source, user_id=None, session_key=None, chat_id=None, chat_type=None, thread_id=None, display_name=None, origin_json=None, include_compression_ancestors=False, transport_profile=None):
        return self._lifecycle.record_gateway_session_peer(session_id, source=source, user_id=user_id, session_key=session_key, chat_id=chat_id, chat_type=chat_type, thread_id=thread_id, display_name=display_name, origin_json=origin_json, include_compression_ancestors=include_compression_ancestors, transport_profile=transport_profile)

    def list_gateway_sessions(self, *, platform=None, active_only=True):
        return self._lifecycle.list_gateway_sessions(platform=platform, active_only=active_only)

    def find_latest_gateway_session_for_peer(self, *, source, user_id=None, session_key=None, chat_id=None, chat_type=None, thread_id=None):
        return self._lifecycle.find_latest_gateway_session_for_peer(source=source, user_id=user_id, session_key=session_key, chat_id=chat_id, chat_type=chat_type, thread_id=thread_id)

    def list_never_active_keyed_sessions(self, *, older_than_days):
        return self._lifecycle.list_never_active_keyed_sessions(older_than_days=older_than_days)

    def find_orphaned_gateway_sessions(self, *, max_gap_s=None):
        return self._lifecycle.find_orphaned_gateway_sessions(max_gap_s=max_gap_s)

    def adopt_orphaned_gateway_session(self, orphan_id, donor_id):
        return self._lifecycle.adopt_orphaned_gateway_session(orphan_id, donor_id)

    def message_storage_state(self, message_id):
        return self._lifecycle.message_storage_state(message_id)

    @property
    def profile_home(self):
        return self._lifecycle.profile_home

    def storage_health(self):
        return self._lifecycle.storage_health()

    def referenced_spillover_names(self):
        return self._lifecycle.referenced_spillover_names()

    def latest_message_preview(self, session_id):
        return self._lifecycle.latest_message_preview(session_id)

    def update_token_counts(self, session_id, input_tokens=0, output_tokens=0, model=None, cache_read_tokens=0, cache_write_tokens=0, reasoning_tokens=0, estimated_cost_usd=None, actual_cost_usd=None, cost_status=None, cost_source=None, pricing_version=None, billing_provider=None, billing_base_url=None, billing_mode=None, api_call_count=0, absolute=False, source=None, task=''):
        return self._usage.update_token_counts(session_id, input_tokens, output_tokens, model, cache_read_tokens, cache_write_tokens, reasoning_tokens, estimated_cost_usd, actual_cost_usd, cost_status, cost_source, pricing_version, billing_provider, billing_base_url, billing_mode, api_call_count, absolute, source, task)

    def record_auxiliary_usage(self, session_id, task, *, model=None, billing_provider=None, billing_base_url=None, input_tokens=0, output_tokens=0, cache_read_tokens=0, cache_write_tokens=0, reasoning_tokens=0, estimated_cost_usd=None, api_call_count=1):
        return self._usage.record_auxiliary_usage(session_id, task, model=model, billing_provider=billing_provider, billing_base_url=billing_base_url, input_tokens=input_tokens, output_tokens=output_tokens, cache_read_tokens=cache_read_tokens, cache_write_tokens=cache_write_tokens, reasoning_tokens=reasoning_tokens, estimated_cost_usd=estimated_cost_usd, api_call_count=api_call_count)

    def update_session_billing_route(self, session_id, *, provider, base_url, billing_mode=None):
        return self._usage.update_session_billing_route(session_id, provider=provider, base_url=base_url, billing_mode=billing_mode)

    def get_recent_session_model_route(self, session_id):
        return self._usage.get_recent_session_model_route(session_id)

    def auxiliary_usage_by_task(self, session_id):
        return self._usage.auxiliary_usage_by_task(session_id)

    def usage_totals(self, *, min_message_count=1, include_archived=False):
        return self._usage.usage_totals(min_message_count=min_message_count, include_archived=include_archived)

    def queue_token_counts(self, session_id, **kwargs):
        return self._usage.queue_token_counts(session_id, **kwargs)

    def flush_token_counts(self, timeout=5.0):
        return self._usage.flush_token_counts(timeout)

    def flush_for_read(self):
        return self._usage.flush_for_read()

    def insights_rows(self, kind, cutoff, source=None):
        return self._usage.insights_rows(kind, cutoff, source)

    def analytics_rows(self, kind, cutoff):
        return self._usage.analytics_rows(kind, cutoff)

    def get_meta(self, key):
        return self._usage.get_meta(key)

    def set_meta(self, key, value, *, cursor=None):
        return self._usage.set_meta(key, value, cursor=cursor)

    def list_meta_prefix(self, prefix):
        return self._usage.list_meta_prefix(prefix)

    def is_kanban_owned_session(self, session_id):
        return self._usage.is_kanban_owned_session(session_id)

    def export_session(self, session_id, include_compacted=False, include_inactive=False):
        return self._transfer.export_session(session_id, include_compacted, include_inactive)

    def export_session_lineage(self, session_id, include_compacted=False, include_inactive=False):
        return self._transfer.export_session_lineage(session_id, include_compacted, include_inactive)

    def export_all(self, source=None, include_compacted=False, include_inactive=False):
        return self._transfer.export_all(source, include_compacted, include_inactive)

    def import_sessions(self, payload):
        return self._transfer.import_sessions(payload)

    def distinct_session_cwds(self, include_archived=False):
        return self._transfer.distinct_session_cwds(include_archived)

    def cron_run_identity(self, session_id):
        return self._transfer.cron_run_identity(session_id)

    def list_cron_job_runs(self, job_id, limit=20, offset=0):
        return self._transfer.list_cron_job_runs(job_id, limit, offset)

    def list_skill_scaffolded_sessions(self, limit=200):
        return self._transfer.list_skill_scaffolded_sessions(limit)

    def find_foreign_import(self, origin):
        return self._transfer.find_foreign_import(origin)

    def import_foreign_history(self, origin, messages, *, title, cwd, profile):
        return self._transfer.import_foreign_history(origin, messages, title=title, cwd=cwd, profile=profile)

    def adopt_session_lineage_from(self, donor_db, session_id, *, retire_donor=True):
        return self._transfer.adopt_session_lineage_from(donor_db, session_id, retire_donor=retire_donor)

    def export_session_for_move(self, session_id):
        return self._transfer.export_session_for_move(session_id)

    def import_moved_session(self, payload, *, profile_name):
        return self._transfer.import_moved_session(payload, profile_name=profile_name)

    def delete_moved_session(self, session_id):
        return self._transfer.delete_moved_session(session_id)

    def find_crossed_profile_sessions(self, owner):
        return self._transfer.find_crossed_profile_sessions(owner)

    def _ledgered_session_ids(self):
        return self._transfer._ledgered_session_ids()

    def list_gateway_routing_rows(self):
        return self._transfer.list_gateway_routing_rows()

    def find_profile_less_telegram_topic_rows(self):
        return self._transfer.find_profile_less_telegram_topic_rows()

    def count_messages_all(self, session_id):
        return self._transfer.count_messages_all(session_id)

    def relabel_sessions_to_key_profile(self, ids):
        return self._transfer.relabel_sessions_to_key_profile(ids)

    def sever_crossed_parents(self, ids):
        return self._transfer.sever_crossed_parents(ids)

    def rekey_legacy_main_sessions(self, ids, profile):
        return self._transfer.rekey_legacy_main_sessions(ids, profile)

    def delete_gateway_routing_rows(self, rows):
        return self._transfer.delete_gateway_routing_rows(rows)

    def insert_gateway_routing_rows_if_absent(self, rows):
        return self._transfer.insert_gateway_routing_rows_if_absent(rows)

    def relabel_telegram_topic_rows(self, rows):
        return self._transfer.relabel_telegram_topic_rows(rows)

    def key_profiles_for_chat(self, platform, chat_id):
        return self._transfer.key_profiles_for_chat(platform, chat_id)

    def create_session(self, session_id, source, **kwargs):
        return self._catalog.create_session(session_id, source, **kwargs)

    def ensure_session(self, session_id, source='unknown', model=None, **kwargs):
        return self._catalog.ensure_session(session_id, source, model, **kwargs)

    def get_session(self, session_id):
        return self._catalog.get_session(session_id)

    def end_session(self, session_id, end_reason):
        return self._catalog.end_session(session_id, end_reason)

    def reopen_session(self, session_id):
        return self._catalog.reopen_session(session_id)

    def transcript_read_snapshot(self):
        return self._context.transcript_read_snapshot()
    MAX_TITLE_LENGTH = SessionCatalog.MAX_TITLE_LENGTH
    TITLE_SOURCE_DERIVED = SessionCatalog.TITLE_SOURCE_DERIVED
    TITLE_SOURCE_LLM = SessionCatalog.TITLE_SOURCE_LLM
    TITLE_SOURCE_USER = SessionCatalog.TITLE_SOURCE_USER
    CANONICAL_BOT_CHAT_TITLE = SessionCatalog.CANONICAL_BOT_CHAT_TITLE
    _ORPHAN_ADOPTION_MAX_GAP_S = SessionLifecycle._ORPHAN_ADOPTION_MAX_GAP_S
