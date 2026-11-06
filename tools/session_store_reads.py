"""Small profile-owned reads shared by local tools and authenticated compute RPC."""


def owns_result(db, owner, parent):
    return db.get_compression_tip(parent) == owner


def persisted_session(db, session_id):
    return session_id if db.get_session(session_id) else None


def cron_run_usage(db, job_id, execution_id):
    run = next((row for row in db.list_cron_job_runs(job_id, limit=50)
        if row.get("cron_execution_id") == execution_id), None)
    if run is None:
        return {}
    rows = [db.get_session(sid) or {} for sid in db.get_compression_chain(run["id"])]
    model = next((row["model"] for row in reversed(rows) if row.get("model")), None)
    return {"api_calls": sum(int(row.get("api_call_count") or 0) for row in rows), **({"model": model} if model else {})}
