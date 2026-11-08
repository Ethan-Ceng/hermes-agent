"""The gateway drains the owning Profile's selected durable delivery queue."""


def drain_delivery_queue(adapters, loop):
    from cron import scheduler
    from cron.delivery_queue import _path, drain
    from hermes_cli.db_setup import storage_backend
    # Native housekeeping must not create an unused SQLite queue; PG has no queue file.
    if storage_backend() == "sqlite" and not _path().exists():
        return 0

    def send(job, content, for_failure):
        error = scheduler._deliver_result(job, content, adapters=adapters, loop=loop, for_failure=for_failure)
        if not error and for_failure and not job.get("_notification_all_targets_suppressed"):
            scheduler._mark_incident_alerted(job.get("_failure_incident_id"))
        return error

    return drain(send)
