"""Gateway routing entry points for the selected store."""

import json

from hermes_db.domains.sessions.postgres.operations import gateway
from hermes_db.domains.sessions.postgres.queries import gateway as repo
from hermes_state_gateway import SessionGatewayMixin


class SessionGateway:
    session_gateway_runtime = staticmethod(SessionGatewayMixin.session_gateway_runtime)

    def purge_profile_state(self, profile):
        from hermes_db.integration.postgres.operations.profile_purge import purge
        with self._write() as conn:
            return purge(conn, self.scope, profile)

    def rekey_profile_state(self, old_name, new_name):
        from hermes_db.domains.sessions.postgres.operations.gateway_rekey import rekey
        with self._write() as conn:
            return rekey(conn, self.scope, old_name, new_name)

    def save_gateway_routing_entry(self, session_key, entry_json, *, scope=""):
        with self._write() as conn:
            if session_key and entry_json:
                gateway.save_route(conn, self.scope, session_key, entry_json, namespace=scope)

    def replace_gateway_routing_entries(self, entries, *, scope=""):
        with self._write() as conn:
            return gateway.replace_routes(conn, self.scope, entries, namespace=scope)

    def load_gateway_routing_entries(self, *, scope=""):
        with self._read() as conn:
            return {row["session_key"]: row["entry_json"] for row in repo.routing_rows(conn, self.scope, scope)}

    def gateway_routing_entry_for_session(self, session_id):
        with self._read() as conn:
            for row in repo.routing_rows(conn, self.scope):
                try:
                    entry = json.loads(row["entry_json"])
                except (ValueError, TypeError, RecursionError):
                    continue
                if isinstance(entry, dict) and entry.get("session_id") == session_id:
                    return entry
        return None

    def retire_gateway_routes(self, session_ids, *, namespace, expiring=()):
        ids = sorted({str(sid) for sid in session_ids if sid})
        with self._write() as conn:
            if ids:
                gateway.retire_routes(conn, self.scope, ids, namespace=namespace, expiring=expiring)
