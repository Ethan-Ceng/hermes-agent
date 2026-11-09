"""An immutable per-attempt proof carried across the network-send await."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class DeliveryClaim:
    store_id: str
    obligation_id: str
    instance_id: str = field(repr=False)
    token: str = field(repr=False)

    def __str__(self):
        return self.obligation_id
