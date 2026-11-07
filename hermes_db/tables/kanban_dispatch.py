"""A store-wide token lease protects automatic dispatch budgets across Boards."""

from sqlalchemy import BigInteger, Column, Text

from hermes_db.tables.metadata import scoped_table

dispatch_leases = scoped_table("kanban_dispatch_leases", Column("token", Text, nullable=False),
                              Column("lease_until", BigInteger, nullable=False), key=())
