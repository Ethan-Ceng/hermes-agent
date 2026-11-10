"""Real PG Bot Chat tips remain discoverable and deferred Cron output survives restart."""

from contextlib import closing
import json
from types import SimpleNamespace

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def _bot(home, session_id):
    from hermes_cli.db_sessions import open_session_store
    with closing(open_session_store(home / "state.db")) as store:
        store.create_session(session_id, "gui")
        store.set_session_title(session_id, "Bot Chat")


def _ready(monkeypatch):
    from hermes_cli import gateway_runtime
    endpoint = SimpleNamespace(instance_id="verified-test-owner")
    monkeypatch.setattr(gateway_runtime, "discover_gateway_endpoint", lambda *args, **kwargs:
                        SimpleNamespace(state="ready", endpoint=endpoint))


def test_pg_bot_owner_uses_its_real_tip_after_ambient_profile_switch(pg_profiles, monkeypatch):
    from tools.bot_live_delivery import find_canonical_live_owner
    with pg_profiles("target") as target:
        _bot(target, "target-chat")
    with pg_profiles("sender") as sender:
        _bot(sender, "sender-chat")
        _ready(monkeypatch)
        owner = find_canonical_live_owner(target)
        assert owner is not None and owner["session_id"] == "target-chat"
        assert owner["profile_home"] == str(target)
        assert not (target / "state.db").exists()


def test_deferred_output_reopens_and_hands_off_to_pg_bot(pg_profiles, monkeypatch):
    from cron import bot_chat_legacy as pending
    from tools import bot_live_delivery as delivery
    with pg_profiles("target") as target:
        _bot(target, "target-chat")
    with pg_profiles("sender") as sender:
        pending.defer("delivery-once", {"id": "job"}, "durable output", target, for_failure=False)
    from hermes_cli.db_setup import _owning_profile
    _ready(monkeypatch)
    sent = []
    def receive(home, owner, message, **fields):
        sent.append((home, owner["session_id"], fields["delivery_id"]))
        return {"status": "queued"}
    monkeypatch.setattr(delivery, "deliver_to_live_owner", receive)
    with _owning_profile(sender):
        pending.drain_legacy_pending()
        pending.drain_legacy_pending()
    assert sent == [(target, "target-chat", "delivery-once")]
    record = json.loads((sender / "cron/bot_chat_pending/delivery-once.json").read_text(encoding="utf-8"))
    assert record["status"] == "transferred" and record["receipt_status"] == "queued"
