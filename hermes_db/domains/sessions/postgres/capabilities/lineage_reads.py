"""Native lineage reads for delegation and prompt-cache identities."""

from hermes_db.domains.sessions.postgres.queries import retirement, sessions as repo
from hermes_db.core.values import model_config


class SessionLineageReads:
    @staticmethod
    def _is_explicit_fork_child_row(row, *, include_reset=False):
        if row.get('source') == 'tool':
            return True
        cfg = model_config(row.get('model_config'))
        names = ('_branched_from', '_delegate_from', '_reset_from') if include_reset else ('_branched_from', '_delegate_from')
        markers = [cfg.get(name) for name in names]
        parent = row.get('parent_session_id')
        return parent in markers if parent else any(marker is not None for marker in markers)

    def get_tool_rotation_root(self, session_id):
        with self._read() as conn:
            row, seen = repo.raw_session(conn, self.scope, session_id), {session_id}
            while row and row['source'] == 'tool':
                parent_id = row['parent_session_id']
                if not parent_id or parent_id in seen or self._is_explicit_fork_child_row({**row, 'source': None}, include_reset=True):
                    break
                parent = repo.raw_session(conn, self.scope, parent_id)
                if not parent or parent['source'] != 'tool' or parent['end_reason'] != 'compression':
                    break
                seen.add(parent_id)
                row = parent
            return row['id'] if row else session_id

    def delegate_descendant_ids(self, session_id):
        with self._read() as conn:
            seeds, seen, current = [], set(), session_id
            while current and current not in seen:
                seen.add(current)
                row = repo.raw_session(conn, self.scope, current)
                cfg = model_config(row['model_config']) if row else {}
                if cfg.get('_delegate_from'):
                    break
                seeds.append(current)
                if not row or cfg.get('_branched_from'):
                    break
                current = row['parent_session_id']
            found, frontier = [], seeds
            while frontier:
                children = [sid for sid in retirement.delegate_children(conn, self.scope, frontier) if sid not in found]
                # Each marked child contributes its compression continuations, even when a legacy
                # continuation has no marker of its own.
                frontier = [sid for sid in retirement.compression_members(conn, self.scope, children)
                            if sid not in found] if children else []
                found.extend(frontier)
            return found
