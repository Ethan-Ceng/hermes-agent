"""Explicit Core effects for private in-transaction authorization and settlement.

These trusted handlers receive a scoped connection and must only perform local
database work. Legacy sqlite3 callbacks are rejected, never executed on PG.
"""

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class CoreEffect:
    apply: Callable


def invoke(effect, conn, scope, *args):
    if effect is None:
        return
    if not isinstance(effect, CoreEffect):
        raise TypeError("PostgreSQL transaction callbacks require an explicit CoreEffect")
    return effect.apply(conn, scope, *args)
