"""Runtime binding over the same Session context; it never owns a pool or closes the owner."""
from contextlib import contextmanager

class RuntimeContext:
    def __init__(self, session_context, collect_retired_media):
        self.session = session_context
        self._collect_retired_media = collect_retired_media

    @property
    def scope(self):
        return self.session.scope

    def read(self):
        return self.session.read()

    @contextmanager
    def write(self):
        with self.session.profile.activate(), self.session.write() as conn:
            yield conn

    def collect_retired_media(self):
        return self._collect_retired_media()
