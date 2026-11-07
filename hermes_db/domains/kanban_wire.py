"""Closed JSON value codec for the existing Kanban DTOs, without dynamic type loading."""

import base64
from dataclasses import asdict, dataclass

_DTO_NAMES = {"Task", "Run", "Comment", "Attachment", "Event"}


@dataclass(frozen=True)
class CommandRefusal:
    name: str
    arguments: tuple

    def raise_error(self):
        from hermes_cli import kanban_db as kb
        factories = {name: getattr(kb, name) for name in ("HallucinatedCardsError", "EmptyCompletionError",
                     "LiveClaimError", "ArtifactPreservationError", "AttachmentTooLarge")}
        factories["ValueError"] = ValueError
        raise factories[self.name](*self.arguments)


def pack(value):
    from hermes_cli import kanban_db as kb
    if value is None or type(value) in (str, int, float, bool):
        return {"kind": "scalar", "value": value}
    if isinstance(value, bytes):
        return {"kind": "bytes", "value": base64.b64encode(value).decode("ascii")}
    if isinstance(value, CommandRefusal):
        return {"kind": "refusal", "value": {"name": value.name, "arguments": pack(value.arguments)}}
    if isinstance(value, dict):
        return {"kind": "dict", "value": {key: pack(item) for key, item in value.items()}}
    if isinstance(value, (list, tuple)):
        return {"kind": "tuple" if isinstance(value, tuple) else "list", "value": [pack(item) for item in value]}
    name = type(value).__name__
    if name in _DTO_NAMES and type(value) is getattr(kb, name):
        return {"kind": name, "value": pack(asdict(value))}
    raise TypeError("Unsupported Kanban RPC value")


def unpack(value):
    from hermes_cli import kanban_db as kb
    if not isinstance(value, dict) or set(value) != {"kind", "value"}:
        raise ValueError("Invalid Kanban RPC value")
    kind, data = value["kind"], value["value"]
    if kind == "scalar" and (data is None or type(data) in (str, int, float, bool)):
        return data
    if kind == "bytes" and isinstance(data, str):
        return base64.b64decode(data, validate=True)
    if kind == "refusal" and isinstance(data, dict):
        return CommandRefusal(data["name"], unpack(data["arguments"]))
    if kind == "dict" and isinstance(data, dict):
        return {key: unpack(item) for key, item in data.items()}
    if kind in {"list", "tuple"} and isinstance(data, list):
        items = [unpack(item) for item in data]
        return tuple(items) if kind == "tuple" else items
    if kind in _DTO_NAMES:
        return getattr(kb, kind)(**unpack(data))
    raise ValueError("Invalid Kanban RPC value")
