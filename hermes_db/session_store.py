"""PG business facade. Connections and transactions belong to each operation."""

from contextlib import contextmanager

from hermes_db.errors import StorageClosedError
from hermes_db.operations import sessions as operations
from hermes_db.repositories import sessions as repo
from hermes_db.session_metadata import SessionMetadata
from hermes_db.session_queries import SessionQueries
from hermes_db.session_titles import SessionTitles
from hermes_db.session_topics import SessionTopics
from hermes_db.session_usage import SessionUsage
from hermes_db.session_messages import SessionMessages
from hermes_db.session_message_reads import SessionMessageReads
from hermes_db.session_message_edits import SessionMessageEdits
from hermes_db.session_message_lookup import SessionMessageLookup
from hermes_db.session_message_reactions import SessionMessageReactions
from hermes_db.session_message_results import SessionMessageResults
from hermes_db.session_leases import SessionLeases
from hermes_db.session_compression import SessionCompression
from hermes_db.session_compression_state import SessionCompressionState
from hermes_db.session_gateway import SessionGateway
from hermes_db.session_heartbeats import SessionHeartbeats
from hermes_db.session_handoffs import SessionHandoffs
from hermes_db.session_gateway_peers import SessionGatewayPeers
from hermes_db.session_retirement import SessionRetirement
from hermes_db.session_rewrites import SessionRewrites
from hermes_db.session_housekeeping import SessionHousekeeping
from hermes_db.session_portability import SessionPortability
from hermes_db.session_prompt_refresh import SessionPromptRefresh
from hermes_db.session_portability_queries import SessionPortabilityQueries
from hermes_db.session_search import SessionSearch
from hermes_db.session_health import SessionHealth
from hermes_db.session_maintenance import SessionMaintenance
from hermes_db.session_profile_moves import SessionProfileMoves
from hermes_db.session_profile_repair import SessionProfileRepair
from hermes_db.session_analytics import SessionAnalytics
from hermes_db.session_bookkeeping import SessionBookkeeping
from hermes_db.session_recall_views import SessionRecallViews
from hermes_db.session_read_snapshot import SessionReadSnapshots, pinned_connection
from hermes_db.session_transcript_pages import SessionTranscriptPages
from hermes_db.session_picker_reads import SessionPickerReads
from hermes_db.session_lineage_reads import SessionLineageReads


class PostgresSessionStore(SessionMetadata, SessionQueries, SessionTitles, SessionTopics, SessionUsage,
                           SessionMessages, SessionMessageReads, SessionMessageEdits, SessionMessageLookup,
                           SessionMessageReactions, SessionMessageResults, SessionLeases, SessionCompression,
                           SessionCompressionState, SessionGateway, SessionHeartbeats, SessionHandoffs, SessionGatewayPeers,
                           SessionRetirement, SessionRewrites, SessionHousekeeping, SessionPortability, SessionPromptRefresh,
                           SessionPortabilityQueries, SessionSearch, SessionHealth, SessionMaintenance, SessionProfileMoves,
                           SessionProfileRepair, SessionAnalytics, SessionBookkeeping, SessionRecallViews, SessionReadSnapshots,
                           SessionTranscriptPages, SessionPickerReads, SessionLineageReads):
    def __init__(self, transactions, scope):
        from hermes_constants import profile_name_for_home
        from hermes_db.usage_writer import UsageWriter
        from hermes_db.integration.profile_context import OwnedProfileContext

        self._transactions = transactions
        self._scope = scope
        scope.require_store_id()
        self._own_profile = profile_name_for_home(scope.profile_home)
        self._closed = False
        self._profile = OwnedProfileContext(scope)
        self._usage_writer = UsageWriter(self.update_token_counts, self._profile)

    @property
    def scope(self):
        return self._scope

    @contextmanager
    def _read(self):
        self._assert_open()
        pinned = pinned_connection(self)
        if pinned is not None:
            yield pinned
            return
        with self._transactions.read() as conn:
            yield conn

    @contextmanager
    def _write(self):
        self._assert_open()
        with self._transactions.write() as conn:
            yield conn

    def _assert_open(self):
        if self._closed:
            raise StorageClosedError("Session store is closed")

    def create_session(self, session_id, source, **kwargs):
        self._assert_open()
        return operations.create(self._transactions, self.scope, session_id, source, own_profile=self._own_profile, **kwargs)

    def ensure_session(self, session_id, source="unknown", model=None, **kwargs):
        return self.create_session(session_id, source, model=model, **kwargs)

    def get_session(self, session_id):
        self.flush_for_read()
        with self._read() as conn:
            return repo.get_session(conn, self.scope, session_id)

    def end_session(self, session_id, end_reason):
        self._assert_open()
        operations.end(self._transactions, self.scope, session_id, end_reason)

    def reopen_session(self, session_id):
        self._assert_open()
        operations.reopen(self._transactions, self.scope, session_id)

    def close(self):
        if self._closed:
            return
        try:
            self._usage_writer.close()
        finally:
            self._closed = True
