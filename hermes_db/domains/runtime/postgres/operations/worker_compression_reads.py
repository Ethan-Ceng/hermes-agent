"""Concrete Worker lineage reads share the receipt's Core connection."""
from hermes_db.domains.sessions.postgres.support.message_codec import codec
from hermes_db.domains.runtime.postgres.operations.worker_handlers import _fields
from hermes_db.domains.sessions.postgres.queries import messages, sessions
from hermes_state_runtime import RuntimeStoreError, _text

class ReadView:

    def __init__(self, conn, scope):
        self.conn, self.scope = (conn, scope)

    def get_session(self, session_id):
        return sessions.get_session(self.conn, self.scope, session_id)

    def readable_ids(self, assigned):
        ancestors, current = ([], assigned)
        while current:
            if current in ancestors:
                raise RuntimeError('Conversation ancestry contains a cycle')
            ancestors.append(current)
            row = sessions.raw_session(self.conn, self.scope, current)
            current = row['parent_session_id'] if row else None
        return list(reversed(ancestors)) + self.get_compression_chain(assigned)

    def authorize(self, assigned, target):
        _text(target)
        if target not in self.readable_ids(assigned):
            raise RuntimeStoreError('permission_denied')

    def get_compression_chain(self, session_id):
        return lineage_reads.get_compression_chain(self.conn, self.scope, session_id)

    def get_compression_tip(self, session_id):
        return lineage_reads.get_compression_tip(self.conn, self.scope, session_id)

    def get_compression_lineage(self, session_id):
        return lineage_reads.get_compression_lineage(self.conn, self.scope, session_id)

    def get_conversation_root(self, session_id):
        return lineage_reads.get_conversation_root(self.conn, self.scope, session_id)

    def resolve_resume_session_id(self, session_id):
        return lineage_reads.resolve_resume_session_id(self.conn, self.scope, session_id)

    def latest_conversation_boundary(self, session_key, source):
        return lineage_reads.latest_conversation_boundary(self.conn, self.scope, session_key, source)

    def declared_scope_identity(self, session_id):
        return lineage_reads.declared_scope_identity(self.conn, self.scope, session_id)

    def get_tool_rotation_root(self, session_id):
        return lineage_reads.get_tool_rotation_root(self.conn, self.scope, session_id)

def context(conn, scope, session_id, payload):
    _fields(payload, ('target',))
    view = ReadView(conn, scope)
    view.authorize(session_id, payload['target'])
    return {'session': view.get_session(payload['target'])}

def lineage(conn, scope, session_id, payload):
    _fields(payload, ('target',))
    view, target = (ReadView(conn, scope), payload['target'])
    view.authorize(session_id, target)
    return {'readable_ids': view.readable_ids(session_id), 'lineage': view.get_compression_lineage(target), 'root': view.get_conversation_root(target), 'tip': view.get_compression_tip(target), 'resume': view.resolve_resume_session_id(target), 'identity': view.declared_scope_identity(target), 'tool_root': view.get_tool_rotation_root(target)}

def boundary(conn, scope, session_id, payload):
    _fields(payload, ('session_key', 'source'))
    view = ReadView(conn, scope)
    row = view.get_session(session_id)
    if (row['session_key'], row['source']) != (payload['session_key'], payload['source']):
        raise RuntimeStoreError('permission_denied')
    return {'value': view.latest_conversation_boundary(payload['session_key'], payload['source'])}

def history(conn, scope, session_id, payload):
    _fields(payload, ('target', 'include_ancestors', 'include_inactive', 'repair_alternation', 'include_row_ids', 'include_compacted'))
    if any((type(value) is not bool for key, value in payload.items() if key != 'target')):
        raise RuntimeStoreError('invalid_params')
    target = payload['target']
    ReadView(conn, scope).authorize(session_id, target)
    ids = messages.resume_lineage(conn, scope, target) if payload['include_ancestors'] else [target]
    conditions = _active_filter(payload['include_inactive'], payload['include_compacted'])
    display = payload['include_compacted'] and (not payload['include_inactive'])
    rows = messages.display_set(conn, scope, ids) if display else messages.select_rows(conn, scope, ids, *conditions)
    if payload['include_compacted']:
        rows = codec._dedupe_display_generations(rows, drop_removed=display)
    return {'messages': codec._rows_to_conversation(rows, session_id=target, include_ancestors=payload['include_ancestors'], repair_alternation=payload['repair_alternation'], include_row_ids=payload['include_row_ids'])}
from hermes_db.domains.sessions.postgres.queries import lineage_reads
from hermes_db.domains.sessions.postgres.messages import _active_filter
