"""Content I/O between two authorization snapshots, without a held connection."""

from gateway import hosted_room_attachments as native
from hermes_db.domains.rooms.attachments.postgres.metadata import select_committed


class AttachmentReaders:
    def _selection(self, room_id, attachment_id, recipient_member_id, event_id, viewer=False):
        return dict(room_id=native._identifier(room_id, label="room_id"), attachment_id=native._attachment_id(attachment_id),
            recipient_member_id=native._identifier(recipient_member_id, label="recipient_member_id") if recipient_member_id is not None else "",
            normalized_event=native._identifier(event_id, label="event_id") if event_id is not None else None, viewer=viewer)

    def _selected(self, selection, authority=None):
        now = float(self.clock())
        with self._store() as store:
            return select_committed(store, **selection, now=now, authority=authority)

    def _after_read(self, row, selection, authority=None):
        current = self._selected(selection, authority)
        if any(current[key] != row[key] for key in ("blob_id", "sha256", "size", "event_id")):
            raise native.AttachmentNotFoundError("attachment changed during viewer read")
        return current

    def read(self, *, room_id, attachment_id, recipient_member_id, event_id=None, viewer=False):
        selection = self._selection(room_id, attachment_id, recipient_member_id, event_id, viewer)
        row = self._selected(selection)
        data = self._read_blob(blob_id=row["blob_id"], size=row["size"], sha256=row["sha256"])
        return native.AttachmentData(self._metadata(self._after_read(row, selection)), data)

    def describe(self, *, room_id, attachment_id, recipient_member_id, event_id):
        recipient_member_id = native._identifier(recipient_member_id, label="recipient_member_id")
        event_id = native._identifier(event_id, label="event_id")
        selection = self._selection(room_id, attachment_id, recipient_member_id, event_id)
        return self._metadata(self._selected(selection))

    def read_range(self, *, room_id, attachment_id, recipient_member_id, event_id, offset, length):
        recipient_member_id = native._identifier(recipient_member_id, label="recipient_member_id")
        event_id = native._identifier(event_id, label="event_id")
        selection = self._selection(room_id, attachment_id, recipient_member_id, event_id)
        if type(offset) is not int or type(length) is not int or offset < 0 or length <= 0:
            raise native.AttachmentError("attachment range must be non-negative integers")
        row = self._selected(selection)
        if offset >= row["size"]:
            raise native.AttachmentError("attachment range starts past the end")
        data = self._read_blob_range(blob_id=row["blob_id"], size=row["size"], offset=offset, length=length)
        return native.AttachmentData(self._metadata(self._after_read(row, selection)), data)

    def read_viewer(self, *, room_id, attachment_id, event_id=None, recipient_member_id=None, authority_gateway_id, authority_epoch):
        selection = self._selection(room_id, attachment_id, recipient_member_id, event_id, True)
        gateway = native._identifier(authority_gateway_id, label="authority_gateway_id")
        if isinstance(authority_epoch, bool) or not isinstance(authority_epoch, int) or authority_epoch < 1:
            raise native.AttachmentError("authority_epoch must be a positive integer")
        authority = dict(room_id=selection["room_id"], authority_gateway_id=gateway, authority_epoch=authority_epoch)
        row = self._selected(selection, authority)
        data = self._read_blob(blob_id=row["blob_id"], size=row["size"], sha256=row["sha256"])
        return native.AttachmentData(self._metadata(self._after_read(row, selection, authority)), data)
