"""Kanban receipts workflow; original connection, fence and off-connection effect boundaries are preserved."""
import json
import time
from sqlalchemy import select
from hermes_db.domains.kanban.postgres import repository as repo
from hermes_db.tables.kanban_commands import command_receipts as receipts
from hermes_db.domains.runtime.values import RuntimeStoreError

class CommandReplay(Exception):

    def __init__(self, result):
        self.result = result

def refusal(error, store):
    values = store.result_values
    if isinstance(error, values.hallucinated_cards_error):
        return store.codec.refusal('HallucinatedCardsError', (error.phantom, error.completing_task_id))
    if isinstance(error, values.empty_completion_error):
        return store.codec.refusal('EmptyCompletionError', (error.task_id,))
    if isinstance(error, values.live_claim_error):
        return store.codec.refusal('LiveClaimError', (error.task_id,))
    name = type(error).__name__ if isinstance(error, (values.artifact_preservation_error, values.attachment_too_large)) else 'ValueError'
    return store.codec.refusal(name, (str(error),))

class CommandReceipt:

    def __init__(self, command_id, request_digest):
        self.command_id = command_id
        self.request_digest = request_digest
        self.recorded_on = None
        self.committed = False

    def check_replay(self, conn, store):
        row = conn.execute(select(receipts).where(repo.scope(receipts, store), receipts.c.command_id == self.command_id)).mappings().one_or_none()
        if row is not None:
            if row['request_digest'] != self.request_digest:
                raise RuntimeStoreError('admission_conflict')
            raise CommandReplay(store.codec.unpack(json.loads(bytes(row['result']))))

    def record(self, conn, store, result):
        if not self.committed:
            conn.execute(receipts.insert().values(**repo.owner(store), command_id=self.command_id, request_digest=self.request_digest, result=json.dumps(store.codec.pack(result), ensure_ascii=True, allow_nan=False).encode(), created_at=int(time.time())))
            self.recorded_on = conn
        return result

    def after_commit(self, conn):
        if self.recorded_on is conn:
            self.committed = True
            self.recorded_on = None
