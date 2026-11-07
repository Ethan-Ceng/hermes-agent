"""Gateway consumers retain the owning Profile and immutable Board generation."""

import asyncio
from types import SimpleNamespace
import pytest

from gateway.config import Platform
from gateway.run import GatewayRunner
from gateway.kanban_watchers_common import _to_thread_process_service
from gateway.kanban_watchers_dispatcher import _KanbanDispatcher, _DispatcherSettings
from gateway.kanban_watchers_notifier import _Collector, _KanbanNotification
from hermes_cli import kanban_db as kb, kanban_db_connect as kbc, kanban_db_notify as notify

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def test_dispatcher_identity_follows_board_generation(pg_profiles):
    dispatcher = _KanbanDispatcher(kb, _DispatcherSettings(60, 0, None, 2, 0, True, None, None))
    with pg_profiles("one"):
        kb.create_board("release")
        original = dispatcher.board_db_fingerprint("release")
        kb.remove_board("release")
        kb.create_board("release")
        replacement = dispatcher.board_db_fingerprint("release")
        assert original != replacement
        assert kb.read_board_metadata("release")["db_path"] is None
    with pg_profiles("two"):
        kb.create_board("release")
        assert dispatcher.board_db_fingerprint("release") not in (original, replacement)


def test_notifier_rewind_keeps_owner_and_does_not_follow_reused_slug(pg_profiles):
    runner = GatewayRunner.__new__(GatewayRunner)
    runner.adapters = {Platform.TELEGRAM: SimpleNamespace()}
    runner._kanban_dispatcher_lock_handle = object()
    with pg_profiles("one"):
        kb.create_board("release")
        with kbc.connect_closing(board="release") as store:
            task = kb.create_task(store, title="deliver", idempotency_key="same")
            notify.add_notify_sub(store, task_id=task, platform="telegram", chat_id="chat")
            kb.complete_task(store, task, summary="done")
        deliveries = _Collector(runner, kb, notifier_profile=None, gc_due=False, gc_retention_days=30).collect()
        delivery, = deliveries
        notification = _KanbanNotification(runner, delivery, platform_cls=Platform, sub_fail_counts={})
        # Delivery occurs off-turn and may run while another routed Profile is active.
        with pg_profiles("two"):
            asyncio.run(notification.rewind())
        with kbc.connect_closing(board="release") as reopened:
            assert notify.list_notify_subs(reopened, task)[0]["last_event_id"] == delivery["old_cursor"]
        kb.remove_board("release")
        kb.create_board("release")
        with kbc.connect_closing(board="release") as replacement:
            assert notify.list_notify_subs(replacement) == []
        from hermes_db.errors import StorageConfigurationError
        with pytest.raises(StorageConfigurationError, match="generation"):
            asyncio.run(notification.rewind())


def test_process_thread_preserves_profile_but_clears_child_mutation_marker(pg_profiles):
    from agent.delegation_context import delegated_child_context
    with pg_profiles("one"), kbc.connect_closing() as store:
        task = kb.create_task(store, title="service")
        def service():
            with kbc.connect_closing() as reopened:
                return kb.add_comment(reopened, task, "service", "off-turn")
        with delegated_child_context("service/child:1"):
            asyncio.run(_to_thread_process_service(service))
        assert kb.list_comments(store, task)[0].body == "off-turn"
