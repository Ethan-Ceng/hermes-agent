"""Concrete application capabilities for Kanban; SQL workflows receive only the ones they use."""
from contextlib import contextmanager
from functools import wraps
from importlib import import_module

from hermes_db.domains.kanban.api import BoardResource
from hermes_db.domains.resource import DomainResource
from hermes_db.errors import StorageConfigurationError


class KanbanApplicationContext:
    def __init__(self, scope):
        self.scope = scope

    @contextmanager
    def activate(self):
        from hermes_cli.db_setup import _owning_profile
        with _owning_profile(self.scope.profile_home):
            yield


class KanbanProfilePolicy:
    def __init__(self, context):
        self._context = context

    def normalize_task_skills(self, skills):
        from hermes_cli.kanban_db import _normalize_task_skills
        with self._context.activate():
            return _normalize_task_skills(skills)

    def project_branch_name(self, project_obj, task_id, title):
        from hermes_cli.kanban_db import _project_branch_name
        with self._context.activate():
            return _project_branch_name(project_obj, task_id, title)

    def resolve_project_link(self, conn, project_id, project_source_task_id, workspace_kind, workspace_path):
        from hermes_cli.kanban_db import _resolve_project_link
        with self._context.activate():
            return _resolve_project_link(conn, project_id, project_source_task_id, workspace_kind, workspace_path)

    def explicit_board_slug(self, board):
        from hermes_cli.kanban_db import _explicit_board_slug
        with self._context.activate():
            return _explicit_board_slug(board)

    def get_current_board(self):
        from hermes_cli.kanban_db import get_current_board
        with self._context.activate():
            return get_current_board()

    def set_current_board(self, slug):
        from hermes_cli.kanban_db import set_current_board
        with self._context.activate():
            return set_current_board(slug)

    def clear_current_board(self):
        from hermes_cli.kanban_db import clear_current_board
        with self._context.activate():
            return clear_current_board()

    def resolve_claim_ttl_seconds(self, ttl_seconds=None):
        from hermes_cli.kanban_db import _resolve_claim_ttl_seconds
        with self._context.activate():
            return _resolve_claim_ttl_seconds(ttl_seconds)

    def resolve_crash_grace_seconds(self):
        from hermes_cli.kanban_db import _resolve_crash_grace_seconds
        with self._context.activate():
            return _resolve_crash_grace_seconds()

    def list_profiles_on_disk(self):
        from hermes_cli.kanban_db import list_profiles_on_disk
        with self._context.activate():
            return list_profiles_on_disk()

    def assert_not_delegated_child_mutation(self, path=None):
        from hermes_cli.kanban_db import _assert_not_delegated_child_mutation
        with self._context.activate():
            return _assert_not_delegated_child_mutation(path)

    def swarm_context(self, root_id, goal):
        from hermes_cli.kanban_swarm import _swarm_context
        with self._context.activate():
            return _swarm_context(root_id, goal)


    def respawn_primary_guard(self, error, latest, lane, now):
        from hermes_cli.kanban_respawn_policy import primary_guard
        with self._context.activate():
            return primary_guard(error, latest, lane, now)

    def respawn_history_guard(self, successes, events, comments):
        from hermes_cli.kanban_respawn_policy import history_guard
        with self._context.activate():
            return history_guard(successes, events, comments)


class KanbanProcesses:
    def __init__(self, context):
        self._context = context

    def claimer_id(self):
        from hermes_cli.kanban_db import _claimer_id
        with self._context.activate():
            return _claimer_id()

    def host_prefix(self):
        from hermes_cli.kanban_db import _host_prefix
        with self._context.activate():
            return _host_prefix()

    def claim_is_live(self, trow):
        from hermes_cli.kanban_db import _claim_is_live
        with self._context.activate():
            return _claim_is_live(trow)

    def pid_alive(self, pid):
        from hermes_cli.kanban_db import _pid_alive
        with self._context.activate():
            return _pid_alive(pid)

    def worker_alive(self, pid, started_at):
        from hermes_cli.kanban_db import _worker_alive
        with self._context.activate():
            return _worker_alive(pid, started_at)

    def worker_survived_termination(self, termination):
        from hermes_cli.kanban_db import _worker_survived_termination
        with self._context.activate():
            return _worker_survived_termination(termination)

    def terminate_reclaimed_worker(self, pid, claim_lock, *, signal_fn=None, started_at=None):
        from hermes_cli.kanban_db import _terminate_reclaimed_worker
        with self._context.activate():
            return _terminate_reclaimed_worker(pid, claim_lock, signal_fn=signal_fn, started_at=started_at)

    def dispatch_once_locked(self, conn, *, spawn_fn=None, ttl_seconds=None, dry_run=False, max_spawn=None, max_in_progress=None, failure_limit=2, stale_timeout_seconds=0, board=None, default_assignee=None, max_in_progress_per_profile=None, reconcile_orphans=True, dispatch_permit=None):
        from hermes_cli.kanban_db_dispatch import _dispatch_once_locked
        with self._context.activate():
            return _dispatch_once_locked(conn, spawn_fn=spawn_fn, ttl_seconds=ttl_seconds, dry_run=dry_run, max_spawn=max_spawn, max_in_progress=max_in_progress, failure_limit=failure_limit, stale_timeout_seconds=stale_timeout_seconds, board=board, default_assignee=default_assignee, max_in_progress_per_profile=max_in_progress_per_profile, reconcile_orphans=reconcile_orphans, dispatch_permit=dispatch_permit)

    def profile_exists_fn(self):
        from hermes_cli.kanban_db_dispatch import _profile_exists_fn
        with self._context.activate():
            return _profile_exists_fn()

    def default_spawn(self, task, workspace, *, board=None, board_owner=None):
        from hermes_cli.kanban_db_dispatch import _default_spawn
        with self._context.activate():
            return _default_spawn(task, workspace, board=board, board_owner=board_owner)

    def call_spawn_fn(self, spawn_fn, task, workspace, board):
        from hermes_cli.kanban_db_dispatch import _call_spawn_fn
        with self._context.activate():
            return _call_spawn_fn(spawn_fn, task, workspace, board)

    def process_fingerprint(self, pid):
        from hermes_cli.kanban_db_dispatch import _process_fingerprint
        with self._context.activate():
            return _process_fingerprint(pid)

    def classify_dead_worker(self, pid, claimer, exit_code=None, *, task_id=None, board=None):
        from hermes_cli.kanban_db_dispatch import _classify_dead_worker
        with self._context.activate():
            return _classify_dead_worker(pid, claimer, exit_code, task_id=task_id, board=board)

    def owner_reclaim_blocked(self, conn, task_id, *, crash_sweep=False):
        from hermes_cli.kanban_owner_recovery import owner_reclaim_blocked
        with self._context.activate():
            return owner_reclaim_blocked(conn, task_id, crash_sweep=crash_sweep)

    def managed_run_exit_code(self, conn, task_id, worker_pid, claim_lock):
        from hermes_cli.kanban_owner_recovery import managed_run_exit_code
        with self._context.activate():
            return managed_run_exit_code(conn, task_id, worker_pid, claim_lock)

    def apply_attempt_note(self, conn, task_id, pid, dead):
        from hermes_cli.kanban_owner_recovery import apply_attempt_note
        with self._context.activate():
            return apply_attempt_note(conn, task_id, pid, dead)

    def owner_reclaim_blocked_after_kill(self, conn, task_id, *, signalled):
        from hermes_cli.kanban_owner_recovery import owner_reclaim_blocked_after_kill
        with self._context.activate():
            return owner_reclaim_blocked_after_kill(conn, task_id, signalled=signalled)

    def reclaim_error(self, conn, task_id, claim_lock):
        from hermes_cli.kanban_owner_recovery import reclaim_error
        with self._context.activate():
            return reclaim_error(conn, task_id, claim_lock)

    def record_crash_summary(self, blocked, limited):
        from hermes_cli.kanban_db_dispatch import detect_crashed_workers
        detect_crashed_workers._last_auto_blocked = blocked
        detect_crashed_workers._last_rate_limited = limited


class KanbanObservers:
    def __init__(self, context):
        self._context = context

    def fire_kanban_lifecycle_hook(self, event, task_id, **fields):
        from hermes_cli.kanban_db import _fire_kanban_lifecycle_hook
        with self._context.activate():
            return _fire_kanban_lifecycle_hook(event, task_id, **fields)

    def fire_dispatch_tick_hook(self, result, *, board=None, dry_run=False):
        from hermes_cli.kanban_db import _fire_dispatch_tick_hook
        with self._context.activate():
            return _fire_dispatch_tick_hook(result, board=board, dry_run=dry_run)

    def fire_worker_spawned_hook(self, conn, task, workspace_path, pid, *, board=None):
        from hermes_cli.kanban_db import _fire_worker_spawned_hook
        with self._context.activate():
            return _fire_worker_spawned_hook(conn, task, workspace_path, pid, board=board)

    def fire_task_hook(self, event, task, task_id, run_id, **fields):
        from hermes_cli.kanban_db import _fire_task_hook
        with self._context.activate():
            return _fire_task_hook(event, task, task_id, run_id, **fields)

    def kanban_observer_consumed(self, event):
        from hermes_cli.kanban_db import _kanban_observer_consumed
        with self._context.activate():
            return _kanban_observer_consumed(event)

class KanbanFiles:
    def __init__(self, context):
        self._context = context

    def discard_staged_copies(self, copies, attachment_dir):
        from hermes_cli.kanban_db import _discard_staged_copies
        with self._context.activate():
            return _discard_staged_copies(copies, attachment_dir)

    def merge_completion_prose_artifacts(self, conn, task_id, metadata, *, summary, result):
        from hermes_cli.kanban_db import _merge_completion_prose_artifacts
        with self._context.activate():
            return _merge_completion_prose_artifacts(conn, task_id, metadata, summary=summary, result=result)

    def persist_scratch_completion_artifacts(self, conn, task_id, metadata, *, attachment_dir=None):
        from hermes_cli.kanban_db import _persist_scratch_completion_artifacts
        with self._context.activate():
            return _persist_scratch_completion_artifacts(conn, task_id, metadata, attachment_dir=attachment_dir)

    def task_attachments_dir(self, task_id, board=None):
        from hermes_cli.kanban_db import task_attachments_dir
        with self._context.activate():
            return task_attachments_dir(task_id, board)

    def workspaces_root(self, board=None):
        from hermes_cli.kanban_db import workspaces_root
        with self._context.activate():
            return workspaces_root(board)

    def board_dir(self, board=None):
        from hermes_cli.kanban_db import board_dir
        with self._context.activate():
            return board_dir(board)

    def read_board_metadata(self, board=None):
        from hermes_cli.kanban_db import read_board_metadata
        with self._context.activate():
            return read_board_metadata(board)

    def read_metadata_file(self, board=None):
        from hermes_cli.kanban_db_boards import _read_metadata_file
        with self._context.activate():
            return _read_metadata_file(board)

    def write_metadata_file(self, board, *, name=None, description=None, icon=None, color=None, archived=None, default_workdir=None, project_id=None):
        from hermes_cli.kanban_db_boards import _write_metadata_file
        with self._context.activate():
            return _write_metadata_file(board, name=name, description=description, icon=icon, color=color, archived=archived, default_workdir=default_workdir, project_id=project_id)

    def finish_import(self, store, row):
        from hermes_cli.kanban_storage_transfer import finish_import
        with self._context.activate():
            return finish_import(store, row)

    def resolve_worktree_workspace(self, task, *, board=None):
        from hermes_cli.kanban_db_workspace import _resolve_worktree_workspace
        with self._context.activate():
            return _resolve_worktree_workspace(task, board=board)

    def resolve_workspace(self, task, *, board=None):
        from hermes_cli.kanban_db_workspace import resolve_workspace
        with self._context.activate():
            return resolve_workspace(task, board=board)

    def maybe_emit_scratch_tip(self, conn, task_id, workspace_kind):
        from hermes_cli.kanban_db_workspace import _maybe_emit_scratch_tip
        with self._context.activate():
            return _maybe_emit_scratch_tip(conn, task_id, workspace_kind)

    def is_managed_scratch_path(self, p):
        from hermes_cli.kanban_db_workspace import _is_managed_scratch_path
        with self._context.activate():
            return _is_managed_scratch_path(p)

    def is_linked_worktree_checkout(self, path):
        from hermes_cli.kanban_db_workspace import _is_linked_worktree_checkout
        with self._context.activate():
            return _is_linked_worktree_checkout(path)

    def cleanup_worker_tmux(self, conn, task_id):
        from hermes_cli.kanban_db_workspace import _cleanup_worker_tmux
        with self._context.activate():
            return _cleanup_worker_tmux(conn, task_id)

    def release_lsp_clients(self, wt_path):
        from hermes_cli.kanban_db_workspace import release_lsp_clients
        with self._context.activate():
            return release_lsp_clients(wt_path)

    def cleanup_worktree_workspace(self, task_id, path, branch_name=None):
        from hermes_cli.kanban_db_workspace import _cleanup_worktree_workspace
        with self._context.activate():
            return _cleanup_worktree_workspace(task_id, path, branch_name)

    def collect_acceptance(self, contract, published_pr, assignee=None):
        from hermes_cli.kanban_pr_acceptance import collect_acceptance
        with self._context.activate():
            return collect_acceptance(contract, published_pr, assignee)

    def remove_tree(self, path):
        import shutil
        with self._context.activate():
            shutil.rmtree(path)

    def board_path(self, board_id, slug, env_var, leaf):
        from hermes_cli.kanban_storage_owner import BoardFiles, _path
        with self._context.activate():
            return _path(BoardFiles(self._context.scope.profile_home, board_id, slug), env_var, leaf)

    def content_root(self, board_id, slug):
        from hermes_cli.kanban_storage_owner import BoardFiles, content_root
        return content_root(BoardFiles(self._context.scope.profile_home, board_id, slug))

    def terminal_execution(self, binding, execution_id, generation):
        from hermes_cli.db_observations import terminal_execution
        with self._context.activate():
            return terminal_execution(binding, execution_id, generation)




def count_notify_subs(*, board=None, notifier_profiles=None, include_unowned=False, platform=None, chat_id=None, thread_id=None):
    from hermes_cli import kanban_db as kb
    from hermes_cli.db_domains import acquire_profile_domain
    from hermes_db.domains.kanban.postgres.catalog import _lookup
    from hermes_db.domains.kanban.postgres.notify import count_subscriptions
    slug = kb._explicit_board_slug(board) or kb.get_current_board()
    with acquire_profile_domain('kanban_tasks') as store, store.read() as conn:
        row = _lookup(conn, store, slug)
        if row is None or row['archived']:
            return 0
        return count_subscriptions(conn, store.scope, row['board_id'], notifier_profiles=notifier_profiles,
            include_unowned=include_unowned, platform=platform, chat_id=chat_id, thread_id=thread_id)


_KANBAN_MODULES = {
    ('archive', 'archive_task'): 'hermes_cli.kanban_storage_catalog',
    ('artifacts', 'add_attachment'): 'hermes_cli.kanban_storage_files',
    ('artifacts', 'delete_attachment'): 'hermes_cli.kanban_storage_files',
    ('artifacts', 'get_attachment'): 'hermes_db.domains.kanban.postgres.files',
    ('artifacts', 'list_attachments'): 'hermes_db.domains.kanban.postgres.files',
    ('artifacts', 'store_attachment_bytes'): 'hermes_cli.kanban_storage_files',
    ('boards', 'board_exists'): 'hermes_db.domains.kanban.postgres.catalog',
    ('boards', 'create_board'): 'hermes_cli.kanban_storage_catalog',
    ('boards', 'list_boards'): 'hermes_cli.kanban_storage_catalog',
    ('boards', 'read_board_metadata'): 'hermes_cli.kanban_storage_catalog',
    ('boards', 'remove_board'): 'hermes_cli.kanban_storage_catalog',
    ('boards', 'write_board_metadata'): 'hermes_cli.kanban_storage_catalog',
    ('claims', 'claim_review_task'): 'hermes_cli.kanban_storage_claims',
    ('claims', 'claim_task'): 'hermes_cli.kanban_storage_claims',
    ('claims', 'heartbeat_claim'): 'hermes_cli.kanban_storage_claims',
    ('claims', 'heartbeat_worker'): 'hermes_db.domains.kanban.postgres.claims',
    ('claims', 'reclaim_task'): 'hermes_cli.kanban_storage_claims',
    ('completion', 'complete_task'): 'hermes_cli.kanban_storage_completion',
    ('completion_guards', '_flag_phantom_prose_refs'): 'hermes_db.domains.kanban.postgres.completion',
    ('completion_guards', '_gate_created_cards'): 'hermes_db.domains.kanban.postgres.completion',
    ('completion_guards', '_gate_empty_completion'): 'hermes_db.domains.kanban.postgres.completion',
    ('completion_guards', '_scan_prose_for_phantom_ids'): 'hermes_db.domains.kanban.postgres.completion',
    ('completion_guards', '_verify_created_cards'): 'hermes_db.domains.kanban.postgres.completion',
    ('crash_sweeps', 'detect_crashed_workers'): 'hermes_cli.kanban_storage_maintenance',
    ('dashboard', '_parents_blocking_ready'): 'hermes_db.domains.kanban.postgres.catalog',
    ('dashboard', '_set_status_direct'): 'hermes_cli.kanban_storage_catalog',
    ('diagnostic_snapshot', 'diagnostic_snapshot'): 'hermes_db.domains.kanban.postgres.catalog',
    ('dispatch', 'dispatch_once'): 'hermes_cli.kanban_storage_dispatch',
    ('dispatch_lane', '_dispatch_lane_task'): 'hermes_cli.kanban_storage_dispatch',
    ('dispatch_queries', '_apply_default_assignee'): 'hermes_db.domains.kanban.postgres.dispatch',
    ('dispatch_queries', '_count_other_running'): 'hermes_db.domains.kanban.postgres.dispatch',
    ('dispatch_queries', '_has_spawnable'): 'hermes_cli.kanban_storage_dispatch',
    ('dispatch_queries', '_lane_rows'): 'hermes_db.domains.kanban.postgres.dispatch',
    ('dispatch_queries', '_running_per_profile'): 'hermes_db.domains.kanban.postgres.dispatch',
    ('dispatch_queries', 'check_respawn_guard'): 'hermes_cli.kanban_storage_dispatch',
    ('dispatch_queries', 'count_running_tasks'): 'hermes_db.domains.kanban.postgres.dispatch',
    ('events', '_append_event'): 'hermes_db.domains.kanban.postgres.catalog',
    ('failures', '_clear_failure_counter'): 'hermes_db.domains.kanban.postgres.runs',
    ('failures', '_record_task_failure'): 'hermes_db.domains.kanban.postgres.runs',
    ('graph', 'child_ids'): 'hermes_db.domains.kanban.postgres.catalog',
    ('graph', 'decompose_triage_task'): 'hermes_cli.kanban_storage_catalog',
    ('graph', 'link_tasks'): 'hermes_db.domains.kanban.postgres.catalog',
    ('graph', 'parent_ids'): 'hermes_db.domains.kanban.postgres.catalog',
    ('graph', 'recompute_ready'): 'hermes_db.domains.kanban.postgres.catalog',
    ('graph', 'specify_triage_task'): 'hermes_db.domains.kanban.postgres.catalog',
    ('graph', 'task_graph_context'): 'hermes_db.domains.kanban.postgres.catalog',
    ('graph', 'task_graph_contexts'): 'hermes_db.domains.kanban.postgres.catalog',
    ('graph', 'unlink_tasks'): 'hermes_db.domains.kanban.postgres.catalog',
    ('graph', 'unsatisfied_parents'): 'hermes_db.domains.kanban.postgres.catalog',
    ('lease_sweeps', 'reconcile_orphaned_running'): 'hermes_cli.kanban_storage_maintenance',
    ('lease_sweeps', 'release_stale_claims'): 'hermes_cli.kanban_storage_maintenance',
    ('notify', 'add_notify_sub'): 'hermes_db.domains.kanban.postgres.notify',
    ('notify', 'advance_notify_cursor'): 'hermes_db.domains.kanban.postgres.notify',
    ('notify', 'claim_unseen_events_for_sub'): 'hermes_db.domains.kanban.postgres.notify',
    ('notify', 'list_notify_subs'): 'hermes_db.domains.kanban.postgres.notify',
    ('notify', 'purge_stale_done_notify_subs'): 'hermes_db.domains.kanban.postgres.notify',
    ('notify', 'record_notify_ping'): 'hermes_db.domains.kanban.postgres.notify',
    ('notify', 'remove_notify_sub'): 'hermes_db.domains.kanban.postgres.notify',
    ('notify', 'retarget_notify_subs'): 'hermes_db.domains.kanban.postgres.notify',
    ('notify', 'rewind_notify_cursor'): 'hermes_db.domains.kanban.postgres.notify',
    ('notify', 'unseen_events_for_sub'): 'hermes_db.domains.kanban.postgres.notify',
    ('owner_recovery', '_latest_run_event'): 'hermes_db.domains.kanban.postgres.owners',
    ('owner_recovery', '_owner_receipt'): 'hermes_db.domains.kanban.postgres.owners',
    ('owner_recovery', '_task_owner_state'): 'hermes_db.domains.kanban.postgres.owners',
    ('queries', 'active_worker_rows'): 'hermes_db.domains.kanban.postgres.catalog',
    ('queries', 'board_rollups'): 'hermes_db.domains.kanban.postgres.catalog',
    ('queries', 'board_status_counts'): 'hermes_db.domains.kanban.postgres.catalog',
    ('queries', 'events_after'): 'hermes_db.domains.kanban.postgres.catalog',
    ('queries', 'latest_event_id'): 'hermes_db.domains.kanban.postgres.catalog',
    ('queries', 'tasks_by_ids'): 'hermes_db.domains.kanban.postgres.catalog',
    ('reopen', 'invalidate_descendants_for_parent_reopen'): 'hermes_cli.kanban_storage_catalog',
    ('review', 'reopen_review_task'): 'hermes_db.domains.kanban.postgres.review',
    ('review', 'request_changes'): 'hermes_db.domains.kanban.postgres.review',
    ('review', 'request_review'): 'hermes_cli.kanban_storage_review',
    ('runs', '_retry_status_for_run'): 'hermes_db.domains.kanban.postgres.runs',
    ('runs', 'current_run_started_ats'): 'hermes_db.domains.kanban.postgres.runs',
    ('runs', 'get_run'): 'hermes_db.domains.kanban.postgres.runs',
    ('runs', 'goal_run_status'): 'hermes_db.domains.kanban.postgres.runs',
    ('runs', 'latest_run'): 'hermes_db.domains.kanban.postgres.runs',
    ('runs', 'latest_summaries'): 'hermes_db.domains.kanban.postgres.runs',
    ('runs', 'latest_summary'): 'hermes_db.domains.kanban.postgres.runs',
    ('runs', 'list_runs'): 'hermes_db.domains.kanban.postgres.runs',
    ('runs', 'recent_profile_completions'): 'hermes_db.domains.kanban.postgres.runs',
    ('runtime_sweeps', 'detect_stale_running'): 'hermes_cli.kanban_storage_maintenance',
    ('runtime_sweeps', 'enforce_max_runtime'): 'hermes_cli.kanban_storage_maintenance',
    ('swarm', 'create_swarm'): 'hermes_cli.kanban_storage_swarm',
    ('tasks', 'add_comment'): 'hermes_db.domains.kanban.postgres.catalog',
    ('tasks', 'assign_task'): 'hermes_cli.kanban_storage_catalog',
    ('tasks', 'board_stats'): 'hermes_db.domains.kanban.postgres.catalog',
    ('tasks', 'create_task'): 'hermes_cli.kanban_storage_catalog',
    ('tasks', 'delete_archived_task'): 'hermes_db.domains.kanban.postgres.catalog',
    ('tasks', 'delete_task'): 'hermes_db.domains.kanban.postgres.catalog',
    ('tasks', 'edit_task'): 'hermes_cli.kanban_storage_catalog',
    ('tasks', 'gc_events'): 'hermes_db.domains.kanban.postgres.catalog',
    ('tasks', 'get_task'): 'hermes_db.domains.kanban.postgres.catalog',
    ('tasks', 'known_assignees'): 'hermes_cli.kanban_storage_catalog',
    ('tasks', 'list_comments'): 'hermes_db.domains.kanban.postgres.catalog',
    ('tasks', 'list_comments_after'): 'hermes_db.domains.kanban.postgres.catalog',
    ('tasks', 'list_events'): 'hermes_db.domains.kanban.postgres.catalog',
    ('tasks', 'list_tasks'): 'hermes_db.domains.kanban.postgres.catalog',
    ('tasks', 'notify_task_updated'): 'hermes_cli.kanban_storage_catalog',
    ('tasks', 'set_model_override'): 'hermes_cli.kanban_storage_catalog',
    ('tasks', 'set_reasoning_effort'): 'hermes_cli.kanban_storage_catalog',
    ('terminal_workers', 'reap_terminal_workers'): 'hermes_cli.kanban_storage_maintenance',
    ('transitions', 'block_task'): 'hermes_cli.kanban_storage_claims',
    ('transitions', 'promote_task'): 'hermes_db.domains.kanban.postgres.claims',
    ('transitions', 'schedule_task'): 'hermes_db.domains.kanban.postgres.claims',
    ('transitions', 'unblock_task'): 'hermes_db.domains.kanban.postgres.claims',
    ('worker_identity', '_set_worker_pid'): 'hermes_cli.kanban_storage_dispatch',
    ('worker_identity', 'adopt_worker_pid'): 'hermes_cli.kanban_storage_dispatch',
    ('workspaces', '_cleanup_workspace'): 'hermes_cli.kanban_storage_workspaces',
    ('workspaces', '_has_active_children'): 'hermes_db.domains.kanban.postgres.workspaces',
    ('workspaces', '_is_terminal_task'): 'hermes_db.domains.kanban.postgres.workspaces',
    ('workspaces', '_workspace_in_use_by_other'): 'hermes_cli.kanban_storage_workspaces',
    ('workspaces', 'gc_archived_workspaces'): 'hermes_cli.kanban_storage_workspaces',
    ('workspaces', 'set_branch_name'): 'hermes_db.domains.kanban.postgres.workspaces',
    ('workspaces', 'set_workspace_path'): 'hermes_cli.kanban_storage_workspaces',
}

def domain_operation(topic):
    def decorate(sqlite_operation):
        @wraps(sqlite_operation)
        def operation(store, *args, **kwargs):
            from agent.runtime_kanban_storage import WorkerBoardResource
            if isinstance(store, WorkerBoardResource):
                return store.invoke(sqlite_operation.__name__, args, kwargs)
            if isinstance(store, DomainResource):
                if not isinstance(store, BoardResource) or store.settings.backend != "postgresql":
                    raise StorageConfigurationError("Kanban operations require the selected Board store")
                module = import_module(_KANBAN_MODULES[(topic, sqlite_operation.__name__)])
                with store._operation_scope():
                    return getattr(module, sqlite_operation.__name__)(store, *args, **kwargs)
            return sqlite_operation(store, *args, **kwargs)
        return operation
    return decorate

def profile_operation(sqlite_operation):
    @wraps(sqlite_operation)
    def operation(*args, **kwargs):
        from hermes_cli.db_setup import storage_backend
        if storage_backend() == "postgresql":
            kanban_boards = import_module(_KANBAN_MODULES[("boards", sqlite_operation.__name__)])
            from hermes_cli.db_domains import acquire_profile_domain
            with acquire_profile_domain("kanban_tasks") as resource:
                return getattr(kanban_boards, sqlite_operation.__name__)(resource, *args, **kwargs)
        return sqlite_operation(*args, **kwargs)
    return operation

def owner_scoped_operation(file_operation):
    """Shared file orchestration still binds the resource's owning Profile."""
    @wraps(file_operation)
    def operation(store, *args, **kwargs):
        if isinstance(store, DomainResource):
            if not isinstance(store, BoardResource):
                raise StorageConfigurationError("Kanban file operations require a Board resource")
            store._assert_open()
            with store._operation_scope():
                return file_operation(store, *args, **kwargs)
        return file_operation(store, *args, **kwargs)
    return operation

def connect(board=None):
    from hermes_cli import kanban_db as kb
    from hermes_cli.db_domains import acquire_profile_domain
    from hermes_cli.kanban_storage_catalog import resolve_board
    slug = kb._explicit_board_slug(board) or kb.get_current_board()
    with acquire_profile_domain("kanban_tasks") as resource:
        board_id = resolve_board(resource, slug)
        return BoardResource(resource, board_id, slug)
