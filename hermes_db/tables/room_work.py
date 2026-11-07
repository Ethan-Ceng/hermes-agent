"""Passive producer-scoped evidence and exact terminal publication references."""

from sqlalchemy import BigInteger, CheckConstraint, Column, LargeBinary, Text
from hermes_db.tables.metadata import scoped_fk, scoped_table


publications = scoped_table("hosted_room_policy_publications",
    *[Column(name, Text, nullable=False) for name in ("room_id", "kind")], Column("task_id", LargeBinary, nullable=False),
    Column("execution_generation", BigInteger, nullable=False, server_default="0"), Column("seq", BigInteger, nullable=False),
    key=("room_id", "task_id", "kind", "execution_generation"), constraints=(
        scoped_fk(("room_id",), "hosted_rooms", ("room_id",), ondelete="CASCADE"),))


def _evidence(name, *, pending=False):
    columns = [Column("room_id", Text, nullable=False), Column("producer_gateway_id", Text, nullable=False),
        Column("producer_epoch", BigInteger, nullable=False), Column("revision", BigInteger, nullable=False),
        Column("digest", Text, nullable=False), Column("record_json", LargeBinary, nullable=False),
        Column("disposition", Text, nullable=False)]
    if pending:
        columns.extend(Column(field, Text, nullable=False) for field in ("target_install_id", "route_generation", "status"))
    return scoped_table(name, *columns, key=("room_id", "producer_gateway_id", "producer_epoch") + (("target_install_id",) if pending else ()),
        constraints=(scoped_fk(("room_id",), "hosted_rooms", ("room_id",), ondelete="CASCADE"),
            CheckConstraint("disposition IN ('current','superseded_authority','historical','invalid')", name=name + "_disposition")))


source = _evidence("hosted_room_work_records_source")
pending = _evidence("hosted_room_work_records_pending", pending=True)
