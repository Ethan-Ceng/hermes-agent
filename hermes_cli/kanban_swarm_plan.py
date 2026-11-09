"""Backend-independent swarm card fields; no storage or filesystem work."""

def plan_swarm(*, goal, workers, verifier_assignee, synthesizer_assignee, root_title=None,
               verifier_title="Verify swarm outputs", synthesizer_title="Synthesize swarm outputs",
               tenant=None, created_by="swarm-orchestrator", workspace_kind=None, workspace_path=None,
               priority=0, idempotency_key=None):
    from hermes_db.domains.kanban.rules import require_swarm_text as _require_text
    goal = _require_text(goal, "goal")
    verifier_assignee = _require_text(verifier_assignee, "verifier_assignee")
    synthesizer_assignee = _require_text(synthesizer_assignee, "synthesizer_assignee")
    specs = list(workers)
    if not specs:
        raise ValueError("at least one worker is required")
    for index, spec in enumerate(specs, start=1):
        _require_text(spec.profile, f"workers[{index}].profile")
        _require_text(spec.title, f"workers[{index}].title")
    common = dict(created_by=created_by, tenant=tenant, workspace_kind=workspace_kind, workspace_path=workspace_path)
    root = dict(common, title=root_title or f"Swarm: {goal.splitlines()[0][:80]}",
        body="Kanban Swarm v1 planning/root card. This card is completed immediately so parallel workers can "
             f"start while it remains the shared blackboard and audit anchor.\n\nGoal:\n{goal}",
        assignee=created_by, priority=priority, idempotency_key=idempotency_key, initial_status="blocked")
    worker_fields = [dict(common, title=spec.title, body=spec.body or "", assignee=spec.profile,
        priority=spec.priority or priority, skills=spec.skills or None, max_runtime_seconds=spec.max_runtime_seconds) for spec in specs]
    verifier = dict(common, title=verifier_title, body="Review every worker handoff and blackboard update. Gate the swarm: "
        'complete only with metadata {"gate": "pass"} when evidence is sufficient; otherwise block with exact missing work.',
        assignee=verifier_assignee, priority=priority, skills=["requesting-code-review"])
    synthesizer = dict(common, title=synthesizer_title,
        body="Synthesize the verified worker outputs into the final deliverable. Do not start until the verifier has passed the gate.",
        assignee=synthesizer_assignee, priority=priority, skills=["humanizer"])
    return dict(goal=goal, root=root, workers=worker_fields, verifier=verifier, synthesizer=synthesizer, created_by=created_by)
