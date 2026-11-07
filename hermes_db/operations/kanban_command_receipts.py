"""A command's primary effect and result use one Board transaction and one commit verdict."""

import json
import time

from sqlalchemy import select

from hermes_db.domains.kanban_wire import pack, unpack
from hermes_db.repositories import kanban as repo
from hermes_db.tables.kanban_commands import command_receipts as receipts
from hermes_state_runtime import RuntimeStoreError


class CommandReplay(Exception):
    def __init__(self, result):
        self.result = result


class CommandReceipt:
    def __init__(self, command_id, request_digest):
        self.command_id = command_id
        self.request_digest = request_digest
        self.recorded_on = None
        self.committed = False

    def check_replay(self, conn, store):
        row = conn.execute(select(receipts).where(repo.scope(receipts, store),
            receipts.c.command_id == self.command_id)).mappings().one_or_none()
        if row is not None:
            if row["request_digest"] != self.request_digest:
                raise RuntimeStoreError("admission_conflict")
            raise CommandReplay(unpack(json.loads(bytes(row["result"]))))

    def record(self, conn, store, result):
        if not self.committed:
            conn.execute(receipts.insert().values(**repo.owner(store), command_id=self.command_id,
                request_digest=self.request_digest, result=json.dumps(pack(result), ensure_ascii=True, allow_nan=False).encode(),
                created_at=int(time.time())))
            self.recorded_on = conn
        return result

    def after_commit(self, conn):
        if self.recorded_on is conn:
            self.committed = True
            self.recorded_on = None
