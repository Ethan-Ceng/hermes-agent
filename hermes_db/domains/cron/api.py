"""Profile-bound Cron entrypoints; legacy path overrides never select a backend."""







from hermes_db.domains.resource import DomainResource


class CronResource(DomainResource):
    def __init__(self, name, backend, *, executions, incidents, delivery, notes):
        super().__init__(name, backend)
        self.executions = executions
        self.incidents = incidents
        self.delivery = delivery
        self.notes = notes
