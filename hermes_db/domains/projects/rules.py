"""Project slug and path rules shared by native SQLite and PostgreSQL; no storage or configuration I/O."""
from __future__ import annotations
import os
import re
from typing import Optional
SLUG_RE = re.compile('^[a-z0-9][a-z0-9\\-_]{0,63}$')

def slugify(name: str) -> str:
    """Derive a slug candidate from a human name (best-effort)."""
    s = re.sub('[^a-z0-9]+', '-', str(name or '').strip().lower()).strip('-_')
    return s[:64].strip('-_') or 'project'

def normalize_slug(slug: Optional[str]) -> Optional[str]:
    """Lowercase + strip a slug; validate; return ``None`` for empty."""
    s = str(slug).strip().lower() if slug is not None else ''
    if not s:
        return None
    if not SLUG_RE.match(s):
        raise ValueError(f"invalid project slug {slug!r}: must be 1-64 chars, lowercase alphanumerics / hyphens / underscores, not starting with '-' or '_'")
    return s

def normalize_path(path: str) -> str:
    """Absolute, user-expanded, separator-normalized path (no trailing sep)."""
    p = os.path.abspath(os.path.expanduser(str(path).strip()))
    return p.rstrip('/\\') or p

def primary_path_key(path: str) -> str:
    """Comparison key for primary-path dedup (absolute + case/sep-normalized)."""
    return os.path.normcase(normalize_path(path))
