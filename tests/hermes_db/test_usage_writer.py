"""Owned background context, ordered writes, bounded flush and unknown commits."""

import asyncio
from threading import Event

import pytest

from hermes_db.errors import UnknownCommitError
from hermes_db.integration.profile_context import OwnedProfileContext
from hermes_db.scope import DatabaseScope
from hermes_db.domains.sessions.postgres.support.usage_writer import UsageWriter


def test_writer_captures_owner_and_preserves_queue_order(tmp_path):
    from agent.secret_scope import get_secret, reset_secret_scope, set_secret_scope
    from hermes_constants import get_hermes_home, reset_hermes_home_override, set_hermes_home_override

    owner = tmp_path / "owner"
    home = set_hermes_home_override(owner)
    secret = set_secret_scope({"DATABASE_OWNER_KEY": "owner"}, profile_home=str(owner))
    entered, release = Event(), Event()
    written = []

    def apply(session_id, **values):
        entered.set()
        assert release.wait(10)
        written.append((session_id, values["input_tokens"], get_hermes_home(), get_secret("DATABASE_OWNER_KEY")))

    writer = UsageWriter(apply, OwnedProfileContext(DatabaseScope(owner, "owner-store")))
    reset_secret_scope(secret)
    reset_hermes_home_override(home)
    foreign = set_hermes_home_override(tmp_path / "foreign")
    foreign_secret = set_secret_scope({"DATABASE_OWNER_KEY": "foreign"}, profile_home=str(tmp_path / "foreign"))
    try:
        for index in range(3):
            writer.enqueue("s", {"input_tokens": index})
        assert entered.wait(10)
        assert not writer.flush(0)
        release.set()
        assert writer.flush(10)
    finally:
        release.set()
        writer.close()
        reset_secret_scope(foreign_secret)
        reset_hermes_home_override(foreign)
    assert [value[1] for value in written] == [0, 1, 2]
    assert all(value[2] == owner.resolve() and value[3] == "owner" for value in written)


def test_unknown_commit_is_not_replayed_and_is_visible_to_the_barrier(tmp_path, caplog):
    calls = []

    def fail(session_id, **values):
        calls.append(session_id)
        raise UnknownCommitError("private-password")

    writer = UsageWriter(fail, OwnedProfileContext(DatabaseScope(tmp_path, "s")))
    writer.enqueue("s", {})
    with pytest.raises(UnknownCommitError):
        writer.flush(10)
    with pytest.raises(UnknownCommitError):
        writer.close()
    assert calls == ["s"]
    assert "private-password" not in caplog.text


def test_read_barrier_does_not_wait_on_an_asyncio_loop():
    from types import SimpleNamespace
    from hermes_db.domains.sessions.postgres.usage import SessionUsage

    class Writer:
        def flush(self, timeout=5):
            assert timeout == 0
            return False

    reader = SessionUsage(SimpleNamespace(usage_writer=Writer()))

    async def read():
        assert not reader.flush_for_read()

    asyncio.run(read())
