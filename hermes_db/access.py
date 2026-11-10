"""Release and liveness operations for acquired business session views."""


def release_session_store(store):
    from hermes_db.domains.sessions.resource import SessionResource
    if isinstance(store, SessionResource):
        store.close()
    else:
        from hermes_state_registry import release_or_close
        release_or_close(store)


def session_store_is_live(store):
    from hermes_db.domains.sessions.resource import SessionResource
    if isinstance(store, SessionResource):
        return store.is_open
    return getattr(store, "_shared_registry_owned", True) is not False
