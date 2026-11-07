"""Store-scoped attachment metadata; canonical content stays in private files."""

from sqlalchemy import BigInteger, CheckConstraint, Column, Float, LargeBinary, Text, UniqueConstraint
from hermes_db.tables.metadata import scoped_fk, scoped_table

roots = scoped_table("hosted_room_attachment_roots", Column("namespace", Text, nullable=False),
    Column("created_at", Float, nullable=False), key=())
blobs = scoped_table("hosted_room_attachment_blobs", Column("blob_id", Text, nullable=False),
    Column("sha256", Text, nullable=False), Column("size", BigInteger, nullable=False),
    Column("ref_count", BigInteger, nullable=False), Column("created_at", Float, nullable=False), key=("blob_id",),
    constraints=(UniqueConstraint("store_id", "sha256"), CheckConstraint("size>0 AND ref_count>0", name="room_blob_counts")))
attachments = scoped_table("hosted_room_attachments", *[Column(name, Text, nullable=False) for name in (
    "attachment_id", "upload_id", "room_id", "kind", "mime", "sha256", "blob_id", "state")],
    Column("event_id", Text), Column("name", LargeBinary, nullable=False), Column("catalog_name", LargeBinary, nullable=False),
    Column("size", BigInteger, nullable=False), Column("recipient_member_ids_json", LargeBinary, nullable=False),
    Column("viewer_access", BigInteger, nullable=False), Column("created_at", Float, nullable=False),
    Column("updated_at", Float, nullable=False), Column("expires_at", Float), key=("attachment_id",), constraints=(
        UniqueConstraint("store_id", "room_id", "upload_id"), scoped_fk(("blob_id",), "hosted_room_attachment_blobs", ("blob_id",), ondelete="RESTRICT"),
        CheckConstraint("size>0 AND viewer_access IN (0,1)", name="room_attachment_values"),
        CheckConstraint("state IN ('uploaded','committed','disbanded')", name="room_attachment_state")))
cleanup = scoped_table("hosted_room_attachment_cleanup", Column("blob_id", Text, nullable=False),
    Column("namespace", Text, nullable=False), Column("created_at", Float, nullable=False), key=("blob_id",))
