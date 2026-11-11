"""Concrete Cron process facts, profile-bound observers and active-send accounting.

Only callbacks the SQL workflows actually use are composed here; process IDs and
active-send locks remain the original owners, and observers still run after commit.
"""

from hermes_cli.db_scope import OwnedProfileContext

class CronExecutionRuntime:
    def __init__(self, scope):
        self.profile = OwnedProfileContext(scope)

    @property
    def handoff_grace_seconds(self):
        from cron import executions
        return executions.HANDOFF_ADOPTION_GRACE_SECONDS

    @property
    def max_terminal(self):
        from cron import executions
        return executions.MAX_TERMINAL_EXECUTIONS

    @property
    def owner_gone_reason(self):
        from cron import executions
        return executions._OWNER_GONE_REASON

    @property
    def owner_wedged_reason(self):
        from cron import executions
        return executions._OWNER_WEDGED_REASON

    @property
    def process_id(self):
        from cron import executions
        return executions._PROCESS_ID

    def emit_state(self, *args, **kwargs):
        from cron import executions
        with self.profile.activate():
            return executions._emit_execution_state(*args, **kwargs)

    def now(self, *args, **kwargs):
        from cron import executions
        with self.profile.activate():
            return executions._hermes_now(*args, **kwargs)

    def live_owner_stale_after_seconds(self, *args, **kwargs):
        from cron import executions
        with self.profile.activate():
            return executions._live_owner_stale_after_seconds(*args, **kwargs)

    def owner_is_live(self, *args, **kwargs):
        from cron import executions
        with self.profile.activate():
            return executions._owner_is_live(*args, **kwargs)

    def process_start_time(self, *args, **kwargs):
        from cron import executions
        with self.profile.activate():
            return executions._process_start_time(*args, **kwargs)

    def row_owner_live(self, *args, **kwargs):
        from cron import executions
        with self.profile.activate():
            return executions._row_owner_live(*args, **kwargs)

    def stale_age_seconds(self, *args, **kwargs):
        from cron import executions
        with self.profile.activate():
            return executions._stale_age_seconds(*args, **kwargs)

    def record_finish(self, *args, **kwargs):
        from cron import executions
        with self.profile.activate():
            return executions.record_cron_finish(*args, **kwargs)

    @property
    def time(self):
        from cron import executions
        return executions.time

    @property
    def uuid(self):
        from cron import executions
        return executions.uuid

class CronIncidentRuntime:
    def __init__(self, scope):
        self.profile = OwnedProfileContext(scope)

    @property
    def states(self):
        from cron import incidents
        return incidents.INCIDENT_STATES

    def classify_failure_type(self, *args, **kwargs):
        from cron import incidents
        with self.profile.activate():
            return incidents._classify_failure_type(*args, **kwargs)

    def error_signature(self, *args, **kwargs):
        from cron import incidents
        with self.profile.activate():
            return incidents._error_signature(*args, **kwargs)

    def now(self, *args, **kwargs):
        from cron import incidents
        with self.profile.activate():
            return incidents._hermes_now(*args, **kwargs)

    def incident_id(self, *args, **kwargs):
        from cron import incidents
        with self.profile.activate():
            return incidents._incident_id(*args, **kwargs)

    def redact_error(self, *args, **kwargs):
        from cron import incidents
        with self.profile.activate():
            return incidents._redact_error(*args, **kwargs)

class CronDeliveryRuntime:
    def __init__(self, scope):
        self.profile = OwnedProfileContext(scope)

    @property
    def max_terminal(self):
        from cron import delivery_queue
        return delivery_queue.MAX_TERMINAL_DELIVERIES

    @property
    def process_id(self):
        from cron import delivery_queue
        return delivery_queue._PROCESS_ID

    @property
    def terminal(self):
        from cron import delivery_queue
        return delivery_queue._TERMINAL

    def now(self, *args, **kwargs):
        from cron import delivery_queue
        with self.profile.activate():
            return delivery_queue._hermes_now(*args, **kwargs)

    def owner_is_live(self, *args, **kwargs):
        from cron import delivery_queue
        with self.profile.activate():
            return delivery_queue._owner_is_live(*args, **kwargs)

    def process_start_time(self, *args, **kwargs):
        from cron import delivery_queue
        with self.profile.activate():
            return delivery_queue._process_start_time(*args, **kwargs)

    @property
    def logger(self):
        from cron import delivery_queue
        return delivery_queue.logger

    def redact_error(self, *args, **kwargs):
        from cron import delivery_queue
        with self.profile.activate():
            return delivery_queue.redact_sensitive_text(*args, **kwargs)

    def mark_active(self, execution_id, home):
        from cron import delivery_queue
        with delivery_queue._lock:
            delivery_queue._ACTIVE_DELIVERIES.add(delivery_queue._active_key(execution_id, home))

    def is_active(self, execution_id, home):
        from cron import delivery_queue
        with delivery_queue._lock:
            return delivery_queue._active_key(execution_id, home) in delivery_queue._ACTIVE_DELIVERIES

    def settle(self, job_id, execution_id):
        from cron.delivery_outcome import settle_quietly
        with self.profile.activate():
            return settle_quietly(job_id, execution_id)

class CronNoteRuntime:
    def __init__(self, scope):
        self.profile = OwnedProfileContext(scope)

    @property
    def max_job_total_bytes(self):
        from cron import notepad
        return notepad.MAX_JOB_TOTAL_BYTES

    def now(self, *args, **kwargs):
        from cron import notepad
        with self.profile.activate():
            return notepad._hermes_now(*args, **kwargs)

    def validate(self, *args, **kwargs):
        from cron import notepad
        with self.profile.activate():
            return notepad._validate(*args, **kwargs)
