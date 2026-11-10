"""SessionTransfer: explicit scoped session transfer operations sharing one resource context."""
from copy import deepcopy
from sqlalchemy import select, func
from hermes_db.domains.sessions.postgres.support.message_codec import codec, content_from_bytes
from hermes_db.domains.sessions.postgres.operations import imports as portability
from hermes_db.integration.postgres.operations import profile_move, profile_repair
from hermes_db.domains.sessions.import_rules import values
from hermes_db.domains.sessions.postgres.queries import messages as portability_messages, session_queries, sessions as portability_sessions, sessions as portability_queries_sessions, gateway
from hermes_db.tables.conversations import sessions as table, messages as portability_queries_messages, messages as profile_repair_messages, sessions as profile_repair_sessions
from hermes_state_portability import _export_timings
import json
from hermes_db.domains.runtime.postgres.queries import runtime
from hermes_db.tables.runtime import session_admissions
from hermes_db.core.values import decode_text
from hermes_state_keys import CRON_PRINCIPAL_ID, cron_run_from_request
from hermes_db.domains.runtime.receipts import POLICY_PREFIX
from hermes_db.core.values import resource_key
from hermes_db.integration.postgres.queries import profile_repair as repo
from hermes_db.tables.gateway import telegram_dm_topic_bindings as bindings
from hermes_state_profile_repair import session_key_profile

def _export(conn, scope, session, include_compacted=False, include_inactive=False):
    from hermes_db.domains.sessions.postgres.messages import _display_page
    from hermes_db.tables.conversations import messages as rows
    if include_compacted and (not include_inactive):
        transcript = _display_page(conn, scope, session['id'], None, 0, False)
    else:
        conditions = [] if include_inactive else [rows.c.active == 1]
        transcript = portability_messages.select_rows(conn, scope, [session['id']], *conditions)
    public = [codec._row_to_message_dict(row, warn_context='export', summary_flag=True) for row in transcript]
    return {**session, 'messages': public, 'timings': _export_timings(public, session['id'])}

def cron_identity(conn, scope, row):
    identity = cron_run_from_request(row['request_id'])
    if identity is None:
        raw = runtime.meta(conn, scope, POLICY_PREFIX + row['target_session_id'])
        if raw:
            policy = json.loads(raw)['policy']
            job = json.loads(policy['request_json']).get('cron_job', {}).get('id')
            if isinstance(job, str):
                identity = cron_run_from_request(row['request_id'], job)
    return {'cron_job_id': identity[0], 'cron_execution_id': identity[1]} if identity else None

def find_foreign(conn, scope, origin):
    rows = conn.execute(select(table.c.id, table.c.origin_json).where(table.c.store_id == scope.require_store_id(), table.c.source == origin['tool'], table.c.origin_json.is_not(None)))
    for sid, raw in rows:
        imported = json.loads(raw).get('imported_from', {})
        if imported.get('tool') != origin['tool']:
            continue
        foreign = origin.get('foreign_session_id')
        if foreign and foreign == imported.get('foreign_session_id') or (not foreign and imported.get('path') == origin['path']):
            return sid
    return None

class SessionTransfer:

    def __init__(self, context, _after_session_delete, flush_for_read, flush_token_counts):
        self._context = context
        self.__after_session_delete = _after_session_delete
        self._flush_for_read = flush_for_read
        self._flush_token_counts = flush_token_counts

    def export_session(self, session_id, include_compacted=False, include_inactive=False):
        self._flush_for_read()
        with self._context.read() as conn:
            row = portability_sessions.get_session(conn, self._context.scope, session_id)
            return _export(conn, self._context.scope, row, include_compacted, include_inactive) if row else None

    def export_session_lineage(self, session_id, include_compacted=False, include_inactive=False):
        self._flush_for_read()
        with self._context.read() as conn:
            ids = portability_messages.resume_lineage(conn, self._context.scope, session_id)
            rows = portability_sessions.get_sessions(conn, self._context.scope, ids)
            segments = [_export(conn, self._context.scope, rows[sid], include_compacted, include_inactive) for sid in ids if sid in rows]
        if not segments:
            return None
        public = [row for segment in segments for row in segment['messages']]
        return {**segments[-1], 'segments': segments, 'lineage_session_ids': [segment['id'] for segment in segments], 'message_count': len(public), 'messages': public, 'timings': _export_timings(public, session_id)}

    def export_all(self, source=None, include_compacted=False, include_inactive=False):
        self._flush_for_read()
        with self._context.read() as conn:
            statement = select(table.c.id).where(table.c.store_id == self._context.scope.require_store_id())
            if source:
                statement = statement.where(table.c.source == source)
            ids = conn.execute(statement.order_by(session_queries.last_activity(conn).desc(), table.c.started_at.desc(), table.c.id.desc()).limit(100000)).scalars().all()
            rows = {}
            for start in range(0, len(ids), 1000):
                rows.update({row['id']: row for row in session_queries.hydrate(conn, self._context.scope, ids[start:start + 1000])})
            return [_export(conn, self._context.scope, rows[sid], include_compacted, include_inactive) for sid in ids]

    def import_sessions(self, payload):
        if not isinstance(payload, list):
            raise ValueError('sessions must be a list')
        if len(payload) > values._IMPORT_MAX_SESSIONS:
            raise ValueError(f'sessions must contain at most {values._IMPORT_MAX_SESSIONS} entries')
        normalized, errors = values._validate_import_payload(deepcopy(payload))
        if errors:
            return {'ok': False, 'imported': 0, 'skipped': 0, 'detached': 0, 'errors': errors}
        with self._context.write() as conn:
            return portability.import_current(conn, self._context.scope, normalized, ownership=self._context.ownership)

    def distinct_session_cwds(self, include_archived=False):
        conditions = [table.c.store_id == self._context.scope.require_store_id(), table.c.cwd.is_not(None), func.trim(table.c.cwd) != '']
        if not include_archived:
            conditions.append(table.c.archived == 0)
        with self._context.read() as conn:
            rows = conn.execute(select(table.c.cwd, func.count().label('sessions'), func.max(func.coalesce(table.c.ended_at, table.c.started_at, 0)).label('last_active')).where(*conditions).group_by(table.c.cwd))
            return [dict(row) for row in rows.mappings()]

    def cron_run_identity(self, session_id):
        with self._context.read() as conn:
            row = conn.execute(select(session_admissions.c.request_id, session_admissions.c.target_session_id).where(session_admissions.c.store_id == self._context.scope.require_store_id(), session_admissions.c.principal_id == CRON_PRINCIPAL_ID, session_admissions.c.target_session_id == session_id).order_by(session_admissions.c.seq).limit(1)).mappings().one_or_none()
            return cron_identity(conn, self._context.scope, row) if row else None

    def list_cron_job_runs(self, job_id, limit=20, offset=0):
        self._flush_for_read()
        with self._context.read() as conn:
            rows = conn.execute(select(session_admissions.c.target_session_id, session_admissions.c.request_id).join(table, (table.c.store_id == session_admissions.c.store_id) & (table.c.id == session_admissions.c.target_session_id)).where(session_admissions.c.store_id == self._context.scope.require_store_id(), session_admissions.c.principal_id == CRON_PRINCIPAL_ID, session_admissions.c.request_id.startswith('cron:' + job_id + ':', autoescape=True), table.c.source == 'cron').order_by(table.c.started_at.desc(), table.c.id.desc(), session_admissions.c.seq)).mappings()
            found = {}
            for row in rows:
                identity = cron_identity(conn, self._context.scope, row)
                if identity and identity['cron_job_id'] == job_id:
                    found.setdefault(row['target_session_id'], identity)
            ids = list(found)[offset:][:None if limit < 0 else limit]
            return [{**row, **found[row['id']]} for row in session_queries.hydrate(conn, self._context.scope, ids)]

    def list_skill_scaffolded_sessions(self, limit=200):
        from agent.skill_commands import AUTO_LOAD_SCAFFOLD_SQL_LIKE, SKILL_SCAFFOLD_SQL_LIKE
        if int(limit) == 0:
            return []
        first = select(portability_queries_messages.c.content).where(portability_queries_messages.c.store_id == table.c.store_id, portability_queries_messages.c.session_id == table.c.id, portability_queries_messages.c.role == 'user', portability_queries_messages.c.content.is_not(None)).order_by(portability_queries_messages.c.timestamp, portability_queries_messages.c.id).limit(1).scalar_subquery()
        with self._context.read() as conn:
            rows = conn.execute(select(table.c.id, table.c.title, first.label('content')).where(table.c.store_id == self._context.scope.require_store_id(), table.c.title.is_not(None)).order_by(table.c.started_at.desc()))
            found = []
            for sid, title, raw in rows:
                content = content_from_bytes(raw)
                if isinstance(content, str) and content.lower().startswith((SKILL_SCAFFOLD_SQL_LIKE[:-1].lower(), AUTO_LOAD_SCAFFOLD_SQL_LIKE[:-1].lower())):
                    found.append({'id': sid, 'title': decode_text(title), 'content': content})
                    if limit >= 0 and len(found) >= limit:
                        break
            return found

    def find_foreign_import(self, origin):
        with self._context.read() as conn:
            return find_foreign(conn, self._context.scope, origin)

    def import_foreign_history(self, origin, messages, *, title, cwd, profile):
        from hermes_db.domains.sessions.postgres.operations import imports as portability
        from hermes_db.domains.sessions.import_rules import values
        from hermes_state_ids import new_session_id
        sid = new_session_id(hex_len=12)
        normalized, errors = values._validate_import_payload([{'id': sid, 'source': origin['tool'], 'title': title, 'cwd': cwd, 'messages': messages}])
        if errors:
            raise ValueError(errors[0]['error'])
        with self._context.write() as conn:
            portability_queries_sessions.lock_store(conn, self._context.scope, exclusive=True)
            existing = find_foreign(conn, self._context.scope, origin)
            if existing:
                return {'session_id': existing, 'already_imported': True}
            if title is not None and conn.scalar(select(table.c.id).where(table.c.store_id == self._context.scope.require_store_id(), table.c.title == title.encode('utf-8'))):
                normalized[0]['session']['title'] = f'{title} ({sid[-12:]})'
            portability.import_row(conn, self._context.scope, normalized[0]['session'], normalized[0]['messages'])
            portability_queries_sessions.update_session(conn, self._context.scope, sid, {'origin_json': json.dumps({'imported_from': origin}), 'profile_name': profile})
            return {'session_id': sid, 'already_imported': False}


    def export_session_for_move(self, session_id):
        self._flush_token_counts()
        with self._context.profile.activate(), self._context.write() as conn:
            return profile_move.prepare(conn, self._context.scope, session_id, resource_key(self._context.transactions))

    def import_moved_session(self, payload, *, profile_name):
        payload = deepcopy(payload)
        binding = resource_key(self._context.transactions)
        profile_move.validate(payload, self._context.scope, binding)
        with self._context.profile.activate(), self._context.write() as conn:
            return profile_move.import_snapshot(conn, self._context.scope, payload, profile_name, binding)

    def delete_moved_session(self, session_id):
        with self._context.write() as conn:
            deleted = profile_move.retire_source(conn, self._context.scope, session_id)
        if deleted:
            self.__after_session_delete([session_id], reason='profile_repair')
        return deleted

    def find_crossed_profile_sessions(self, owner):
        with self._context.read() as conn:
            return repo.crossed(conn, self._context.scope, owner)

    def _ledgered_session_ids(self):
        with self._context.read() as conn:
            return repo.ledgered_ids(conn, self._context.scope)

    def list_gateway_routing_rows(self):
        with self._context.read() as conn:
            return [{key: value for key, value in row.items() if key != 'store_id'} for row in sorted(gateway.routing_rows(conn, self._context.scope), key=lambda row: (row['scope'], row['session_key']))]

    def find_profile_less_telegram_topic_rows(self):
        with self._context.read() as conn:
            rows = conn.execute(select(bindings.c.chat_id, bindings.c.thread_id, bindings.c.session_key).where(bindings.c.store_id == self._context.scope.require_store_id(), bindings.c.profile_name == 'default').order_by(bindings.c.chat_id, bindings.c.thread_id)).mappings()
            return [{**row, 'key_profile': target} for row in rows if (target := session_key_profile(row['session_key'])) not in (None, 'default')]

    def count_messages_all(self, session_id):
        with self._context.read() as conn:
            return conn.scalar(select(func.count()).select_from(profile_repair_messages).where(profile_repair_messages.c.store_id == self._context.scope.require_store_id(), profile_repair_messages.c.session_id == session_id))

    def relabel_sessions_to_key_profile(self, ids):
        with self._context.write() as conn:
            return profile_repair.repair_sessions(conn, self._context.scope, ids)

    def sever_crossed_parents(self, ids):
        with self._context.write() as conn:
            return profile_repair.repair_sessions(conn, self._context.scope, ids, sever=True)

    def rekey_legacy_main_sessions(self, ids, profile):
        with self._context.write() as conn:
            return profile_repair.repair_sessions(conn, self._context.scope, ids, rekey=profile)

    def delete_gateway_routing_rows(self, rows):
        with self._context.write() as conn:
            return gateway.delete_routes(conn, self._context.scope, rows)

    def insert_gateway_routing_rows_if_absent(self, rows):
        with self._context.write() as conn:
            return profile_repair.insert_routes(conn, self._context.scope, rows)

    def relabel_telegram_topic_rows(self, rows):
        with self._context.write() as conn:
            return profile_repair.repair_topics(conn, self._context.scope, rows)

    def key_profiles_for_chat(self, platform, chat_id):
        with self._context.read() as conn:
            keys = conn.execute(select(profile_repair_sessions.c.session_key).where(profile_repair_sessions.c.store_id == self._context.scope.require_store_id(), profile_repair_sessions.c.source == platform, profile_repair_sessions.c.chat_id == str(chat_id))).scalars()
            return {profile for key in keys if (profile := session_key_profile(key)) is not None}
