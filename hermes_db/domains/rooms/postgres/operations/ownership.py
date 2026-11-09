"""Non-mutating native owner probes on the captured room resource."""

from hermes_db.domains.rooms.postgres.operations.coordination import owner


def probe_native_room_owner(store, *, room_id):
    with store.read() as conn:
        return owner(conn, store.scope, str(room_id)) is not None
