"""A caller-owned session view closes its acquisition, never another caller's store."""


class SessionResource:
    def __init__(self, handle):
        self._handle = handle

    @property
    def scope(self):
        return self._handle.scope

    @property
    def is_open(self):
        return self._handle.is_open

    @property
    def runtime(self):
        return self._handle.runtime

    @property
    def session_store(self):
        return self._handle.sessions

    def __getattr__(self, name):
        return getattr(self._handle.sessions, name)

    def close(self):
        self._handle.close()

    def __enter__(self):
        self._handle.sessions
        return self

    def __exit__(self, *exc):
        self.close()
