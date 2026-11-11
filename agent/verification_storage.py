"""Resolve the evidence owner's backend before touching any ledger file."""


def postgres_resource():
    from agent.runtime_domain_store import worker_resource
    from hermes_cli.db_setup import resolve_db_configuration
    from hermes_cli.db_domains import acquire_domain

    worker = worker_resource('verification')
    if worker is not None:
        return worker
    settings, scope = resolve_db_configuration()
    if settings.backend == "sqlite":
        return None
    return acquire_domain("verification", settings, scope)


def record(resource, evidence, created_at, *, cutoff, per_root_limit, total_limit):
    from agent.runtime_domain_store import WorkerDomainStore
    if isinstance(resource, WorkerDomainStore):
        return resource.command('verification.record', {'evidence': evidence})
    from hermes_db.domains.verification import postgres
    return postgres.record(resource, evidence, created_at, cutoff=cutoff, per_root_limit=per_root_limit, total_limit=total_limit)


def mark_edited(resource, session_id, root, changed, edited_at):
    from agent.runtime_domain_store import WorkerDomainStore
    if isinstance(resource, WorkerDomainStore):
        return resource.command('verification.mark_edited', dict(session_id=session_id, root=root, changed=changed))
    from hermes_db.domains.verification import postgres
    return postgres.mark_edited(resource, session_id, root, changed, edited_at)


def status(resource, session_id, root):
    from agent.runtime_domain_store import WorkerDomainStore
    if isinstance(resource, WorkerDomainStore):
        return resource.query('verification.status', dict(session_id=session_id, root=root))
    from hermes_db.domains.verification import postgres
    return postgres.status(resource, session_id, root)
