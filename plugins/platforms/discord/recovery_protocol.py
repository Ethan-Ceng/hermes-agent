"""Named Discord recovery operations; callers never receive a database connection."""


class RecoveryOperations:
    def probe(self):
        return self._operation("probe", default=False)

    def seen(self, record):
        return self._operation("seen", record=record)

    def attempt(self, record, *, error):
        return self._operation("attempt", record=record, error=error)

    def processing_start(self, record, *, message_id, emoji_ack, now):
        return self._operation("processing_start", record=record, message_id=message_id, emoji_ack=emoji_ack, now=now)

    def complete(self, message_id, *, success, cancelled, now):
        return self._operation("complete", message_id=message_id, success=success, cancelled=cancelled, now=now)

    def response(self, message_id, *, response_id, completed, now):
        return self._operation("response", message_id=message_id, response_id=response_id, completed=completed, now=now)

    def is_complete(self, message_id):
        return self._operation("is_complete", default=False, message_id=message_id)

    def active_claim(self, message_id, *, cutoff):
        return self._operation("active_claim", default=True, message_id=message_id, cutoff=cutoff)

    def attempts_exhausted(self, message_id, *, cap):
        return self._operation("attempts_exhausted", default=False, message_id=message_id, cap=cap)

    def scan_start(self, record):
        return self._operation("scan_start", record=record)

    def scan_complete(self, record):
        return self._operation("scan_complete", record=record)

    def cursor(self, channel_id):
        return self._operation("cursor", channel_id=channel_id)

    def advance_cursor(self, channel_id, *, message_id, now):
        return self._operation("advance_cursor", channel_id=channel_id, message_id=message_id, now=now)
