"""Local artifact identity survives restarts and never relies on a database file."""

import os
from pathlib import Path
import uuid


def owner_id(home, *, create=False):
    path = Path(home) / ".file-store-id"
    try:
        return uuid.UUID(path.read_text(encoding="ascii").strip()).hex
    except FileNotFoundError:
        if not create:
            return None
    except (OSError, ValueError):
        return None
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="ascii") as stream:
            value = uuid.uuid4().hex
            stream.write(value)
        return value
    except FileExistsError:
        return owner_id(home)
    except OSError:
        return None


def identity(path):
    stat = Path(path).lstat()
    return [stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns]
