"""mautrix 0.21.1 CryptoStore and SyncStore backed by shared synchronous Core."""

import asyncio
import os
from contextlib import asynccontextmanager
from dataclasses import replace

from mautrix.client.state_store import SyncStore
from mautrix.crypto.store import CryptoStore

from hermes_db.domains.plugin_storage.matrix.postgres import codec
from hermes_db.errors import StorageClosedError
from hermes_db.domains.plugin_storage.matrix.postgres.operations import accounts, sessions
from hermes_db.core.values import decode_text


class PostgresCryptoStore(CryptoStore, SyncStore):
    def __init__(self, *, account_id, pickle_key, reference, initialize, runtime_factory):
        self.account_id = account_id
        self.pickle_key = pickle_key
        self.reference = reference
        self._initialize = initialize
        self._runtime_factory = runtime_factory
        self.runtime = None
        self._open_lock = asyncio.Lock()
        self._pid = os.getpid()
        from hermes_db.domains.plugin_storage.matrix.postgres.olm_cache import OlmSessions
        self._olm_sessions = OlmSessions(self)

    async def open(self):
        self._assert_owner()
        async with self._open_lock:
            if self.runtime is not None:
                if self.runtime.closed:
                    raise StorageClosedError("Recreate the Matrix store after closing it")
                return
            generation = await asyncio.to_thread(self._initialize, self.reference)
            self.reference = replace(self.reference, generation=generation)
            self.runtime = self._runtime_factory(self.reference)

    async def close(self):
        self._assert_owner()
        if self.runtime is not None:
            await self.runtime.close()

    async def flush(self):
        # Every operation has already committed; there is no buffered persistence.
        await self._call(accounts.account)

    async def _call(self, operation, *, write=False, **arguments):
        self._assert_owner()
        if self.runtime is None:
            raise StorageClosedError("Open Matrix encryption store before use")
        from hermes_db.errors import StorageError
        from hermes_db.domains.plugin_storage.matrix.postgres.failures import remember
        try:
            return await self.runtime.call(operation, write=write, **arguments)
        except StorageError as error:
            remember(error)
            raise

    def _assert_owner(self):
        if self._pid != os.getpid():
            raise StorageClosedError("Recreate Matrix encryption store in its owning process")

    @asynccontextmanager
    async def transaction(self):
        self._assert_owner()
        if self.runtime is None:
            raise StorageClosedError("Open Matrix encryption store before use")
        async with self._olm_sessions.guard():
            writes = self._olm_sessions.writes
            try:
                async with self.runtime.transaction():
                    yield
            except BaseException as error:
                if self._olm_sessions.writes != writes:
                    self._olm_sessions.failed = True
                from hermes_db.errors import StorageError
                from hermes_db.domains.plugin_storage.matrix.postgres.failures import remember
                if isinstance(error, StorageError):
                    remember(error)
                raise

    async def delete(self):
        await self._call(accounts.delete_account, write=True)

    async def get_device_id(self):
        return (await self._call(accounts.account))["device_id"]

    async def put_device_id(self, device_id):
        await self._call(accounts.put_device_id, write=True, device_id=device_id)

    async def get_account(self):
        from mautrix.crypto import OlmAccount
        record = await self._call(accounts.account)
        return None if record["account_pickle"] is None else OlmAccount.from_pickle(record["account_pickle"], self.pickle_key, bool(record["shared"]))

    async def put_account(self, account):
        await self._call(accounts.put_account, write=True, pickle=account.pickle(self.pickle_key), shared=account.shared, identity_key=account.identity_key)

    async def get_next_batch(self):
        return (await self._call(accounts.account))["sync_token"]

    async def put_next_batch(self, next_batch):
        await self._call(accounts.put_next_batch, write=True, next_batch=next_batch)

    async def has_session(self, key):
        self._olm_sessions.require_usable()
        present = await self._call(sessions.has_session, sender_key=key)
        self._olm_sessions.require_usable()
        return present

    async def get_sessions(self, key):
        return await self._olm_sessions.read(key)

    async def get_latest_session(self, key):
        rows = await self._olm_sessions.read(key, latest=True)
        return rows[0] if rows else None

    async def add_session(self, key, session):
        await self._olm_sessions.save(key, session, add=True)

    async def update_session(self, key, session):
        await self._olm_sessions.save(key, session)

    async def put_group_session(self, room_id, sender_key, session_id, session):
        if (room_id, sender_key, session_id) != (session.room_id, session.sender_key, session.id):
            raise ValueError("Matrix inbound session identity differs from its storage key")
        await self._call(sessions.put_group_session, write=True, record=codec.inbound_record(session, self.pickle_key))

    async def get_group_session(self, room_id, session_id):
        return codec.restore_inbound(await self._call(sessions.get_group_session, room_id=room_id, session_id=session_id), self.pickle_key)

    async def has_group_session(self, room_id, session_id):
        return await self._call(sessions.has_group_session, room_id=room_id, session_id=session_id)

    async def redact_group_session(self, room_id, session_id, reason):
        await self._call(sessions.redact_group_session, write=True, room_id=room_id, session_id=session_id, reason=reason)

    async def redact_group_sessions(self, room_id, sender_key, reason):
        return [decode_text(value) for value in await self._call(sessions.redact_group_sessions, write=True, room_id=room_id, sender_key=sender_key, reason=reason)]

    async def redact_expired_group_sessions(self):
        return [decode_text(value) for value in await self._call(sessions.redact_expired_group_sessions, write=True)]

    async def redact_outdated_group_sessions(self):
        return [decode_text(value) for value in await self._call(sessions.redact_outdated_group_sessions, write=True)]

    async def add_outbound_group_session(self, session):
        await self._call(sessions.add_outbound_group_session, write=True, record=codec.outbound_record(session, self.pickle_key))

    async def update_outbound_group_session(self, session):
        await self._call(sessions.update_outbound_group_session, write=True, record=codec.outbound_record(session, self.pickle_key))

    async def get_outbound_group_session(self, room_id):
        return codec.restore_outbound(await self._call(sessions.get_outbound_group_session, room_id=room_id), self.pickle_key)

    async def remove_outbound_group_session(self, room_id):
        await self.remove_outbound_group_sessions([room_id])

    async def remove_outbound_group_sessions(self, rooms):
        await self._call(sessions.remove_outbound_group_sessions, write=True, rooms=rooms)

    async def validate_message_index(self, sender_key, session_id, event_id, index, timestamp):
        return await self._call(accounts.validate_message_index, write=True, sender_key=sender_key, session_id=session_id, event_id=event_id, index=index, timestamp=timestamp)

    async def get_devices(self, user_id):
        rows = await self._call(accounts.get_devices, user_id=user_id)
        return None if rows is None else {row["device_id"]: codec.restore_device(row) for row in rows}

    async def get_device(self, user_id, device_id):
        return codec.restore_device(await self._call(accounts.get_device, user_id=user_id, device_id=device_id))

    async def find_device_by_key(self, user_id, identity_key):
        return codec.restore_device(await self._call(accounts.get_device, user_id=user_id, identity_key=identity_key))

    async def put_devices(self, user_id, devices):
        if any(value.user_id != user_id or value.device_id != key for key, value in devices.items()):
            raise ValueError("Matrix device list contains a different user or device identity")
        await self._call(accounts.put_devices, write=True, user_id=user_id, records=[codec.device_record(value) for value in devices.values()])

    async def filter_tracked_users(self, users):
        return await self._call(accounts.filter_tracked_users, users=users)

    async def get_cross_signing_keys(self, user_id):
        from mautrix.types import CrossSigningUsage, TOFUSigningKey
        return {CrossSigningUsage(row["usage"]): TOFUSigningKey(row["key"], row["first_key"]) for row in await self._call(accounts.get_cross_signing_keys, user_id=user_id)}

    async def put_cross_signing_key(self, user_id, usage, key):
        await self._call(accounts.put_cross_signing_key, write=True, user_id=user_id, usage=usage.value, key=key)

    @staticmethod
    def _signature_fields(target, signer):
        return dict(target_user=target.user_id, target_key=target.key, signer_user=signer.user_id, signer_key=signer.key)

    async def put_signature(self, target, signer, signature):
        await self._call(accounts.put_signature, write=True, fields=self._signature_fields(target, signer), signature=signature)

    async def is_key_signed_by(self, target, signer):
        return await self._call(accounts.is_key_signed_by, fields=self._signature_fields(target, signer))

    async def drop_signatures_by_key(self, signer):
        return await self._call(accounts.drop_signatures_by_key, write=True, user_id=signer.user_id, key=signer.key)
