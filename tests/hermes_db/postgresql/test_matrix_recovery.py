"""Actual fresh-process SDK restores account, group keys and sync without SDK SQL drivers."""

import asyncio
import json
from pathlib import Path
import subprocess
import sys
import pytest
from tests.hermes_db.matrix_support import new_store, sdk_machine

pytestmark = [pytest.mark.integration, pytest.mark.allow_network, pytest.mark.platforms("linux")]


@pytest.mark.asyncio
async def test_actual_new_process_sdk_encrypt_decrypt_recovery_without_sqlite_drivers(pg_profiles):
    from mautrix.crypto import InboundGroupSession, OutboundGroupSession
    from tests.gateway.fixtures.local_recovery_probe import child_env
    with pg_profiles("one") as home:
        store = new_store()
        await store.open()
        try:
            async with sdk_machine(store) as (machine, _):
                outbound = OutboundGroupSession("!room:matrix.test")
                outbound.shared = True
                inbound = InboundGroupSession(outbound.session_key, machine.account.signing_key, machine.account.identity_key, outbound.room_id)
                cipher = outbound.encrypt("new-process group plaintext")
                await store.add_outbound_group_session(outbound)
                await store.put_group_session(inbound.room_id, inbound.sender_key, inbound.id, inbound)
                await store.put_next_batch("new-process\x00🙂")
                fixture = dict(identity=machine.account.identity_keys, room=inbound.room_id, session=inbound.id, cipher=cipher)
                (home / "matrix-fixture.json").write_text(json.dumps(fixture), encoding="utf-8")
        finally:
            await store.close()
        env = child_env()
        env.update(HERMES_HOME=str(home), HOME=str(home), USERPROFILE=str(home), PYTHONPATH=str(Path(__file__).resolve().parents[3]))
        script = Path(__file__).with_name("scenarios") / "matrix_recovery.py"
        result = await asyncio.to_thread(subprocess.run, [sys.executable, str(script)], env=env, capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)
        assert result.returncode == 0, result.stderr
        assert "PG_MATRIX_SDK_RESTART_OK" in result.stdout
        reopened = new_store()
        await reopened.open()
        try:
            assert (await reopened.get_outbound_group_session(inbound.room_id)).message_count == 2
        finally:
            await reopened.close()
