"""Shared failure-budget decisions independent of backend and orchestration."""


def failure_budget(task, failure_limit, force_trip, infrastructure):
    failures = int(task["consecutive_failures"]) + (0 if infrastructure else 1)
    override = task["max_retries"]
    limit, source = (int(override), "task") if override is not None else (int(failure_limit), "dispatcher")
    trip = not infrastructure and (force_trip or failures >= limit)
    return failures, limit, source, trip
