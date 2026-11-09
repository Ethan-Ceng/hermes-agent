"""Current PG-only Profile move entry points; no old database formats are accepted."""

from copy import deepcopy

from hermes_db.integration.transfer.move_values import resource_key
from hermes_db.integration.postgres.operations import profile_move


class SessionProfileMoves:
    def adopt_session_lineage_from(self, donor_db, session_id, *, retire_donor=True):
        from hermes_db.errors import StorageConfigurationError
        from hermes_db.integration.postgres.operations.adoption import adopt
        from hermes_db.domains.sessions.postgres.store import PostgresSessionStore
        from hermes_db.core.session_resource import SessionResource
        if isinstance(donor_db, SessionResource):
            donor_db = donor_db.session_store
        if (not isinstance(donor_db, PostgresSessionStore) or donor_db.scope.store_id == self.scope.store_id
                or resource_key(donor_db._transactions) != resource_key(self._transactions)):
            raise StorageConfigurationError("Adoption requires distinct current PostgreSQL stores in the same shared schema")
        donor_db.flush_token_counts()
        self.flush_token_counts()
        with self._profile.activate(), self._write() as conn:
            return adopt(conn, self.scope, donor_db.scope, session_id, retire_donor=retire_donor)

    def export_session_for_move(self, session_id):
        self.flush_token_counts()
        with self._profile.activate(), self._write() as conn:
            return profile_move.prepare(conn, self.scope, session_id, resource_key(self._transactions))

    def import_moved_session(self, payload, *, profile_name):
        payload = deepcopy(payload)
        binding = resource_key(self._transactions)
        profile_move.validate(payload, self.scope, binding)
        with self._profile.activate(), self._write() as conn:
            return profile_move.import_snapshot(conn, self.scope, payload, profile_name, binding)

    def delete_moved_session(self, session_id):
        with self._write() as conn:
            deleted = profile_move.retire_source(conn, self.scope, session_id)
        if deleted:
            self._after_session_delete([session_id], reason="profile_repair")
        return deleted
