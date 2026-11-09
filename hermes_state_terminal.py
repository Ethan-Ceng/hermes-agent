"""Private terminal-only tombstone queries; never reconstruct executable history.

The authenticated edge supplies the original principal/target/request and frozen
payload. A retired target permits only that exact digest, never fresh admission.
Worker receipt reads additionally require the original private adoption proof.
"""
import hmac
import json

from hermes_state_runtime import ADMITTED_REQUEST_CONFLICT, RuntimeStoreError, _epoch, _row, admission_fingerprint
from hermes_db.domains.runtime.receipts import ADMISSION_PREFIX, WORKER_PREFIX, identity_key
from hermes_db.domains.runtime.values import _json, _secret_digest, _text





# Top-level row key only ``encode_result`` writes. The row's top level is built by the gateway
# (``result``/``usage``), never by the agent or a message, so message fields can't collide with it.








def terminal_api_admissions(conn, request_id):
    """Retired API admissions that carried *request_id*: a deleted session's tombstones, kept for
    the exact-retry horizon, still spend its Idempotency-Key for every other target."""
    return [json.loads(row[0]) for row in conn.execute(
        "SELECT value FROM state_meta WHERE key GLOB ? "
        "AND json_extract(value, '$.principal_id')='api' AND json_extract(value, '$.request_id')=?",
        (ADMISSION_PREFIX + '*', request_id))]


def terminal_admission(conn, admission_id):
    saved = conn.execute('SELECT value FROM state_meta WHERE key=?',
                         (ADMISSION_PREFIX + admission_id,)).fetchone()
    return json.loads(saved[0]) if saved else None


def retry_terminal_admission(db, *, epoch, principal_id, session_id, request_id, payload, intent='queue'):
    """None means a live target; a retired miss/conflict is a definitive refusal.

    This is a read-only identity lookup, not authorization to attach, restore a
    route, or write. HTTP authentication/grant checks must precede this query.
    """
    for value in (principal_id, session_id, request_id):
        _text(value)
    digest = admission_fingerprint(canonical_target=session_id,
        payload={'input': json.loads(_json(payload)), 'intent': intent})
    with db._read_ctx() as conn:
        _epoch(conn, epoch)
        from hermes_db.domains.runtime.receipts import RETIRED_PREFIX
        if not conn.execute('SELECT 1 FROM state_meta WHERE key=?', (RETIRED_PREFIX + session_id,)).fetchone():
            return None
        saved = conn.execute('SELECT value FROM state_meta WHERE key=?',
                             (identity_key(principal_id, session_id, request_id),)).fetchone()
        if saved is None:
            raise RuntimeStoreError('not_found')
        row = terminal_admission(conn, json.loads(saved[0]))
        if row['payload_digest'] != digest:
            raise RuntimeStoreError('admission_conflict', **ADMITTED_REQUEST_CONFLICT)
        return _row(row)


def terminal_worker_receipt(db, *, execution_id, session_id, generation, sequence,
                            adoption_secret, payload_digest):
    """Exact retired producer evidence; possession never reactivates the worker."""
    proof = _secret_digest(adoption_secret)
    with db._read_ctx() as conn:
        saved = conn.execute('SELECT value FROM state_meta WHERE key=?',
                             (WORKER_PREFIX + execution_id,)).fetchone()
        if saved is None:
            raise RuntimeStoreError('not_found')
        worker = json.loads(saved[0])
        if worker['session_id'] != session_id or not hmac.compare_digest(worker['adoption_digest'], proof):
            raise RuntimeStoreError('permission_denied')
        if type(generation) is not int or generation != worker['generation']:
            raise RuntimeStoreError('stale_generation')
        receipt = next((r for r in worker['receipts'] if r['sequence'] == sequence), None)
        if receipt is None:
            raise RuntimeStoreError('stale_generation')
        if receipt['payload_digest'] != payload_digest:
            raise RuntimeStoreError('admission_conflict')
        if receipt['result_json'] is None:
            raise RuntimeStoreError('stale_generation')
        return json.loads(receipt['result_json'])
