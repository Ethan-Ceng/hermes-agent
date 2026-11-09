"""Guard, claim, prepare and spawn without retaining the dispatch coordination connection."""

import logging
from functools import partial

from hermes_db.errors import StorageConfigurationError, StorageError
from hermes_db.domains.kanban.postgres.operations.claims import _claim
from hermes_db.domains.kanban.postgres.operations.dispatch_queries import diagnostic

logger = logging.getLogger("hermes_cli.kanban_db")


def _guard(store, task_id, assignee, result, lane, dry_run, cap, running):
    from hermes_cli import kanban_db_dispatch as dispatch
    exists = dispatch._profile_exists_fn()
    if exists is not None and not exists(assignee):
        result.skipped_nonspawnable.append(task_id)
        if not dry_run:
            diagnostic(store, task_id, "skipped_nonspawnable", {"assignee": assignee}, once=True)
        return False
    if cap is not None and running.get(assignee, 0) >= cap:
        result.skipped_per_profile_capped.append((task_id, assignee, running.get(assignee, 0)))
        return False
    reason = dispatch.check_respawn_guard(store, task_id, lane=lane)
    if reason is not None:
        result.respawn_guarded.append((task_id, reason))
        if not dry_run:
            diagnostic(store, task_id, "respawn_guarded", {"reason": reason})
        return False
    return True


def _workspace(store, claimed):
    from hermes_cli import kanban_db_workspace as workspace
    if claimed.workspace_kind == "worktree":
        path, branch = workspace._resolve_worktree_workspace(claimed, board=store.slug)
        workspace.set_branch_name(store, claimed.id, branch or (claimed.branch_name or "").strip() or f"wt/{claimed.id}")
    else:
        path = workspace.resolve_workspace(claimed, board=store.slug)
    workspace.set_workspace_path(store, claimed.id, str(path))
    workspace._maybe_emit_scratch_tip(store, claimed.id, claimed.workspace_kind)
    return str(path)


def _spawn_failure(store, task, error, result, failure_limit, *, workspace=False):
    from hermes_cli import kanban_db as kb
    from tools.process_registry import RestartSafeScopeUnavailable
    infrastructure = isinstance(error, RestartSafeScopeUnavailable)
    message = f"workspace: {error}" if workspace else str(error)
    if kb._record_task_failure(store, task.id, message, outcome="spawn_failed", failure_limit=failure_limit,
        release_claim=True, end_run=True, infrastructure=infrastructure, expected_run_id=task.current_run_id):
        result.auto_blocked.append(task.id)


def _dispatch_lane_task(store, row, assignee, result, *, lane, dry_run, ttl_seconds, board, failure_limit,
                        spawn_fn, per_profile_cap, per_profile_running, dispatch_permit=None):
    from hermes_cli import kanban_db as kb, kanban_db_dispatch as dispatch
    if dispatch_permit is None:
        raise StorageConfigurationError("Automatic Kanban claims require a dispatch lease")
    task_id = row["id"]
    dispatch_permit.lease.check()
    if not _guard(store, task_id, assignee, result, lane, dry_run, per_profile_cap, per_profile_running):
        return False
    if dry_run:
        result.spawned.append((task_id, assignee, ""))
    else:
        permit = dispatch_permit.for_assignee(assignee, per_profile_cap)
        task = _claim(store, task_id, lane, ttl_seconds, None, dispatch_permit=permit)
        if task is None:
            return False
        try:
            workspace = _workspace(store, task)
        except StorageError:
            raise
        except Exception as error:
            logger.exception("kanban: workspace preparation failed for task %s", task.id)
            _spawn_failure(store, task, error, result, failure_limit, workspace=True)
            return False
        if lane == "review":
            task.skills = list(dict.fromkeys([*(task.skills or []), "sdlc-review"]))
        if not permit.before_spawn(store, task, ttl_seconds):
            return False
        try:
            from hermes_db.domains.kanban.routing.owner import board_reference
            spawn = spawn_fn or partial(dispatch._default_spawn, board_owner=board_reference(store))
            pid = dispatch._call_spawn_fn(spawn, task, workspace, store.slug)
        except StorageError:
            raise
        except Exception as error:
            logger.exception("kanban: worker spawn failed for task %s", task.id)
            _spawn_failure(store, task, error, result, failure_limit)
            return False
        if pid:
            dispatch._set_worker_pid(store, task.id, int(pid), run_id=task.current_run_id, claim_lock=task.claim_lock)
        kb._fire_worker_spawned_hook(store, task, workspace, pid, board=store.slug)
        result.spawned.append((task.id, task.assignee or "", workspace))
    if per_profile_cap is not None and assignee:
        per_profile_running[assignee] = per_profile_running.get(assignee, 0) + 1
    return True
