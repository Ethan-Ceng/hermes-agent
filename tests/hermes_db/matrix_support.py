"""Real SDK constructors shared by Linux Matrix business contracts."""

from contextlib import asynccontextmanager


def new_store(**overrides):
    from hermes_db.matrix_crypto import PostgresCryptoStore
    return PostgresCryptoStore(**dict(dict(account_id="@bot:matrix.test", device_id="DEVICE", homeserver="https://matrix.test", pickle_key="isolated-test-key"), **overrides))


def olm_pair():
    from mautrix.crypto import OlmAccount
    alice, bob = OlmAccount(), OlmAccount()
    bob.generate_one_time_keys(1)
    outbound = alice.new_outbound_session(bob.identity_key, next(iter(bob.one_time_keys["curve25519"].values())))
    message = outbound.encrypt("Olm first message 🙂")
    inbound = bob.new_inbound_session(alice.identity_key, message.body)
    assert inbound.decrypt(message) == "Olm first message 🙂"
    return alice, bob, outbound, inbound


def group_pair(room="!room:matrix.test"):
    from mautrix.crypto import InboundGroupSession, OutboundGroupSession, OlmAccount
    account = OlmAccount()
    outbound = OutboundGroupSession(room)
    outbound.shared = True
    inbound = InboundGroupSession(outbound.session_key, account.signing_key, account.identity_key, room)
    return outbound, inbound


@asynccontextmanager
async def sdk_machine(store, *, device_id=None):
    import aiohttp
    from mautrix.api import HTTPAPI
    from mautrix.client import Client
    from mautrix.client.state_store import MemoryStateStore
    from mautrix.crypto import OlmMachine
    from plugins.platforms.matrix.adapter_crypto import _CryptoStateStore
    async with aiohttp.ClientSession() as session:
        state = MemoryStateStore()
        client = Client(mxid=store.account_id, device_id=device_id or store.reference.owner_device,
            api=HTTPAPI(base_url="https://matrix.test", client_session=session), state_store=state, sync_store=store)
        machine = OlmMachine(client, store, _CryptoStateStore(state, set(), client))
        await machine.load()
        yield machine, client


def current_engine():
    from hermes_cli.db_setup import resolve_db_configuration
    from hermes_db.backends.postgresql.engine import get_engine
    settings, _ = resolve_db_configuration()
    return get_engine(settings.postgresql)
