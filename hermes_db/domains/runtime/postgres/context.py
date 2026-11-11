"""Runtime binding over the same Session context; it never owns a pool or closes the owner."""

class RuntimeContext:
    def __init__(self, session_context, collect_retired_media, worker_handlers):
        self.session = session_context
        self._collect_retired_media = collect_retired_media
        self.worker_handlers = worker_handlers

    @property
    def scope(self):
        return self.session.scope

    def read(self):
        return self.session.read()


    def collect_retired_media(self):
        return self._collect_retired_media()
