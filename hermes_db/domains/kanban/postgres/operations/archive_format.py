"""Strict PG v2 archive data and registered-file validation, without database access."""

import hashlib
import json
from pathlib import Path, PurePosixPath
import re

from hermes_db.domains.kanban.postgres.operations.transfer import FORMAT_VERSION, TABLES


def _json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as error:
        raise ValueError(f"Cannot read Board archive {path.name}") from error


def member_path(root, member):
    if (not isinstance(member, str) or "\\" in member or ":" in member
            or any(part in {"", ".", ".."} for part in member.split("/")) or PurePosixPath(member).is_absolute()):
        raise ValueError("Invalid Board archive attachment member")
    path = root.joinpath(*member.split("/"))
    if not path.resolve().is_relative_to(root.resolve()) or path.is_symlink():
        raise ValueError("Board archive member escapes its root")
    return path


def fingerprint(path):
    digest, size = hashlib.sha256(), 0
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return {"size": size, "sha256": digest.hexdigest()}


def _rows(tables):
    from sqlalchemy import BigInteger
    if not isinstance(tables, dict) or set(tables) != set(TABLES):
        raise ValueError("Board archive must contain all supported data tables")
    for name, table in TABLES.items():
        columns = {column.name: column for column in table.columns if column.name not in {"store_id", "board_id", "path_key"}}
        if not isinstance(tables[name], list):
            raise ValueError("Board archive table must contain rows")
        for row in tables[name]:
            if not isinstance(row, dict) or set(row) != set(columns):
                raise ValueError(f"Board archive {name} has unsupported columns")
            for key, column in columns.items():
                value = row[key]
                valid = value is None and column.nullable
                valid = valid or (type(value) is int if isinstance(column.type, BigInteger) else isinstance(value, str))
                if not valid:
                    raise ValueError(f"Board archive {name}.{key} has an invalid value")
        identities = [(row["parent_id"], row["child_id"]) if name == "task_links" else row["id"] for row in tables[name]]
        if len(set(identities)) != len(identities):
            raise ValueError(f"Board archive {name} contains duplicate identities")


def _validate_proof(member, proof):
    if (not member.startswith("attachments/") or not isinstance(proof, dict) or set(proof) != {"size", "sha256"}
            or type(proof["size"]) is not int or proof["size"] < 0 or not isinstance(proof["sha256"], str)
            or re.fullmatch(r"[0-9a-f]{64}", proof["sha256"]) is None):
        raise ValueError("Invalid Board archive attachment fingerprint")


def _graph(tables):
    from collections import deque
    from hermes_cli.kanban_db import VALID_STATUSES, VALID_WORKSPACE_KINDS
    tasks = {row["id"]: row for row in tables["tasks"]}
    incoming = dict.fromkeys(tasks, 0)
    children = {key: [] for key in tasks}
    for row in tasks.values():
        if row["status"] not in VALID_STATUSES or row["workspace_kind"] not in VALID_WORKSPACE_KINDS:
            raise ValueError("Board archive contains an unsupported task status or workspace kind")
    for edge in tables["task_links"]:
        parent, child = edge["parent_id"], edge["child_id"]
        if parent not in tasks or child not in tasks:
            raise ValueError("Board archive dependency references an unknown task")
        incoming[child] += 1
        children[parent].append(child)
    ready = deque(key for key, count in incoming.items() if count == 0)
    visited = 0
    while ready:
        parent = ready.popleft()
        visited += 1
        for child in children[parent]:
            incoming[child] -= 1
            if incoming[child] == 0:
                ready.append(child)
    if visited != len(tasks):
        raise ValueError("Board archive dependency graph contains a cycle")


def read_archive(root, *, private_stage=False):
    from hermes_cli.kanban_transfer import ARCHIVE_FORMAT
    manifest = _json(root / "manifest.json")
    if (not isinstance(manifest, dict) or manifest.get("format") != ARCHIVE_FORMAT
            or type(manifest.get("format_version")) is not int or manifest["format_version"] != FORMAT_VERSION
            or manifest.get("backend") != "postgresql"):
        raise ValueError("PostgreSQL imports require a PG v2 Board archive; cross-backend migration is unsupported")
    allowed = {"manifest.json", "board.json", "data.json", "attachments", "logs"}
    if private_stage:
        allowed.add(".owner.json")
    if any(path.name not in allowed for path in root.iterdir()):
        raise ValueError("Unexpected member in PG Board archive")
    data = _json(root / "data.json")
    if (not isinstance(data, dict) or set(data) != {"format_version", "tables"}
            or type(data["format_version"]) is not int or data["format_version"] != FORMAT_VERSION):
        raise ValueError("Unsupported Board archive data format")
    tables = data["tables"]
    _rows(tables)
    _graph(tables)
    proofs = manifest.get("files")
    members = {row["stored_path"] for row in tables["task_attachments"]}
    if not isinstance(proofs, dict) or set(proofs) != members:
        raise ValueError("Board archive attachment manifest does not match its rows")
    for member, proof in proofs.items():
        _validate_proof(member, proof)
        path = member_path(root, member)
        if not path.is_file() or fingerprint(path) != proof:
            raise ValueError("Board archive attachment fingerprint mismatch")
    metadata = _json(root / "board.json")
    if not isinstance(metadata, dict):
        raise ValueError("Board archive display metadata must be an object")
    return manifest, tables, metadata
