"""Convert real mautrix values outside database connections, without lossy date coercion."""

from datetime import UTC, datetime, timedelta
import json


def date(value):
    return None if value is None else value.isoformat()


def parse_date(value):
    return None if value is None else datetime.fromisoformat(value)


def epoch(value):
    if value is None:
        return None
    return (value if value.tzinfo else value.replace(tzinfo=UTC)).timestamp()


def duration(value):
    return None if value is None else json.dumps([value.days, value.seconds, value.microseconds])


def parse_duration(value):
    return None if value is None else timedelta(*json.loads(value))


def session_record(key, session, pickle_key):
    return dict(sender_key=key, session_id=session.id, pickle=session.pickle(pickle_key),
        created_at=date(session.creation_time), last_encrypted=date(session.last_encrypted),
        last_decrypted=date(session.last_decrypted), decrypted_order=epoch(session.last_decrypted))


def restore_session(record, pickle_key):
    from mautrix.crypto import Session
    return Session.from_pickle(record["pickle"], pickle_key, parse_date(record["created_at"]),
        parse_date(record["last_encrypted"]), parse_date(record["last_decrypted"]))


def inbound_record(session, pickle_key):
    return dict(room_id=session.room_id, session_id=session.id, sender_key=session.sender_key,
        signing_key=session.signing_key, pickle=session.pickle(pickle_key),
        forwarding_json=json.dumps(session.forwarding_chain), ratchet_json=session.ratchet_safety.json(),
        received_at=date(session.received_at), received_order=epoch(session.received_at),
        max_age_json=duration(session.max_age), max_age_ms=None if session.max_age is None else session.max_age.total_seconds() * 1000,
        max_messages=session.max_messages, is_scheduled=int(session.is_scheduled))


def restore_inbound(record, pickle_key):
    from mautrix.crypto import InboundGroupSession
    from mautrix.crypto.sessions import RatchetSafety
    from mautrix.errors import GroupSessionWithheldError
    from mautrix.types import RoomKeyWithheldCode
    if record is None:
        return None
    if record["pickle"] is None:
        raise GroupSessionWithheldError(record["session_id"], RoomKeyWithheldCode(record["withheld_code"]))
    return InboundGroupSession.from_pickle(record["pickle"], pickle_key, record["signing_key"], record["sender_key"], record["room_id"],
        json.loads(record["forwarding_json"]), RatchetSafety.parse_json(record["ratchet_json"]), parse_date(record["received_at"]),
        parse_duration(record["max_age_json"]), record["max_messages"], bool(record["is_scheduled"]))


def outbound_record(session, pickle_key):
    return dict(room_id=session.room_id, session_id=session.id, pickle=session.pickle(pickle_key), shared=int(session.shared),
        max_age_json=duration(session.max_age), max_age_ms=session.max_age.total_seconds() * 1000,
        max_messages=session.max_messages, message_count=session.message_count,
        created_at=date(session.creation_time), last_used=date(session.use_time))


def restore_outbound(record, pickle_key):
    from mautrix.crypto import OutboundGroupSession
    if record is None:
        return None
    return OutboundGroupSession.from_pickle(record["pickle"], pickle_key, parse_duration(record["max_age_json"]), record["max_messages"],
        parse_date(record["created_at"]), parse_date(record["last_used"]), record["message_count"], record["room_id"], bool(record["shared"]))


def device_record(value):
    return dict(user_id=value.user_id, device_id=value.device_id, identity_key=value.identity_key,
        signing_key=value.signing_key, trust=int(value.trust), deleted=int(value.deleted), name=value.name)


def restore_device(record):
    from mautrix.types import DeviceIdentity, TrustState
    if record is None:
        return None
    return DeviceIdentity(**{key: record[key] for key in ("user_id", "device_id", "identity_key", "signing_key", "name")},
        trust=TrustState(record["trust"]), deleted=bool(record["deleted"]))
