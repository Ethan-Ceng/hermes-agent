"""SQLite ledgers created by explicit scheduler setup and job creation."""


def initialize_cron_stores(profile_home=None) -> None:
    from hermes_constants import get_hermes_home
    from hermes_cli.db_scope import bind_profile_home
    from hermes_cli.db_setup import storage_backend
    from hermes_db.scope import DatabaseScope

    home = get_hermes_home() if profile_home is None else profile_home
    with bind_profile_home(DatabaseScope(home)):
        if storage_backend(home) == "sqlite":
            from cron import delivery_queue, executions, incidents, notepad

            for store in (executions, incidents, notepad, delivery_queue):
                store.initialize()


def publish_job_record(job) -> None:
    from cron import jobs

    from hermes_cli.db_scope import bind_profile_home
    from hermes_cli.db_setup import storage_backend
    from hermes_db.scope import DatabaseScope

    home = jobs._current_cron_store().cron_dir.parent
    with bind_profile_home(DatabaseScope(home)):
        if storage_backend(home) == "sqlite":
            from cron import delivery_queue, executions, incidents, notepad

            stores = (executions, incidents, notepad, delivery_queue)
            missing = {store._sqlite_path() for store in stores if not store._sqlite_path().exists()}
            for store in stores:
                if store._sqlite_path() in missing:
                    store.initialize()
            for store in stores:
                store._connect().close()
    with jobs._jobs_lock():
        jobs.save_jobs(jobs.load_jobs() + [job])
