"""Shared state decisions for typed blocks, independent of SQL dialect."""


def block_transition(kind, reason, source_status, *, prev_kind, prev_recurrences, recurrence_limit):
    payload = {"reason": reason, "kind": kind, "source_status": source_status}
    if kind == "dependency":
        return "todo", "dependency_wait", {"block_kind": kind}, payload
    recurrences = prev_recurrences + 1 if prev_kind == kind else 1
    values = {"block_kind": kind, "block_recurrences": recurrences}
    payload["recurrences"] = recurrences
    if recurrences >= recurrence_limit:
        payload["limit"] = recurrence_limit
        return "triage", "block_loop_detected", values, payload
    return "blocked", "blocked", values, payload
