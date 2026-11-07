"""Persistent subscription inheritance, concurrent delivery claims and owner filters."""

from concurrent.futures import ThreadPoolExecutor
import pytest

from hermes_cli import kanban_db as kb, kanban_db_connect as kbc, kanban_db_notify as notify

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def subscribe(store, task_id, **fields):
    notify.add_notify_sub(store, task_id=task_id, platform="Telegram", chat_id="chat\x00🙂", **fields)


def test_subscription_inheritance_scope_metadata_and_reopen(pg_profiles):
    with pg_profiles("one"):
        kb.create_board("other")
        with kbc.connect_closing() as store:
            parent = kb.create_task(store, title="parent")
            subscribe(store, parent, notifier_profile="owner", user_id="first", delivery_mode="wake",
                      delivery_metadata={"zero": 0, "false": False, "anchor": "🙂\x00"})
            subscribe(store, parent, notifier_profile="other", user_id="second", delivery_metadata={"route": "new"})
            child = kb.create_task(store, title="child", parents=[parent])
            detached = kb.create_task(store, title="creator", creator_task_id=parent)
            linked = kb.create_task(store, title="linked")
            kb.link_tasks(store, parent, linked)
            for task_id in (parent, child, detached, linked):
                row, = notify.list_notify_subs(store, task_id)
                assert row["notifier_profile"] == "owner" and row["user_id"] == "first"
                assert row["delivery_mode"] == "wake"
                assert row["delivery_metadata"] == {"zero": 0, "false": False, "anchor": "🙂\x00", "route": "new"}
            assert notify.count_notify_subs(platform="telegram", chat_id="chat\x00🙂", notifier_profiles=["owner"]) == 4
            assert notify.count_notify_subs(notifier_profiles=["other"]) == 0
            assert notify.count_notify_subs(board="other") == 0
        with kbc.connect_closing() as reopened:
            assert len(notify.list_notify_subs(reopened)) == 4
            assert notify.remove_notify_sub(reopened, task_id=parent, platform="Telegram", chat_id="chat\x00🙂")
    with pg_profiles("two"):
        assert notify.count_notify_subs() == 0


def test_competing_claims_and_rewind_do_not_clobber_later_cursor(pg_profiles):
    with pg_profiles("one"), kbc.connect_closing() as first, kbc.connect_closing() as second:
        task_id = kb.create_task(first, title="events")
        subscribe(first, task_id)
        kb.add_comment(first, task_id, "worker", "one")
        key = dict(task_id=task_id, platform="Telegram", chat_id="chat\x00🙂")
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(notify.claim_unseen_events_for_sub, store, **key) for store in (first, second)]
            claims = [future.result() for future in futures]
        old, new, claimed = next(claim for claim in claims if claim[2])
        assert sum(bool(claim[2]) for claim in claims) == 1
        assert [event.kind for event in claimed] == ["commented"]
        notify.record_notify_ping(first, **key, event_id=new)
        notify.record_notify_ping(first, **key, event_id=old)
        kb.add_comment(second, task_id, "worker", "two")
        later_old, later_new, later = notify.claim_unseen_events_for_sub(second, **key)
        assert later_old == new and len(later) == 1
        assert not notify.rewind_notify_cursor(first, **key, claimed_cursor=new, old_cursor=old)
        assert notify.rewind_notify_cursor(second, **key, claimed_cursor=later_new, old_cursor=later_old)
        assert notify.list_notify_subs(first, task_id)[0]["last_ping_event_id"] == new
        notify.advance_notify_cursor(first, **key, new_cursor=later_new)
        assert notify.unseen_events_for_sub(second, **key)[1] == []
