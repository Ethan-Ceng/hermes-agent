"""Pure Profile identifier normalization and validation; no Profile filesystem or services."""
import re
from hermes_constants import PROFILE_ID_RE as _PROFILE_ID_RE

_RESERVED_NAMES = frozenset({"hermes", "default", "test", "tmp", "root", "sudo"})

_PROFILE_NAME_RULE = (
    "Use lowercase letters, numbers, '-' or '_', starting with a letter or number, "
    "up to 64 characters"
)

def _suggest_profile_name(name: str) -> str:
    """Best-effort valid id derived from *name* (``'My Work'`` -> ``'my-work'``); ``my-work`` if nothing usable."""
    candidate = re.sub(r"[^a-z0-9_-]+", "-", name.strip().lower()).strip("-_")[:64]
    return candidate if _PROFILE_ID_RE.match(candidate) else "my-work"

def _invalid_profile_name_error(name: str) -> ValueError:
    suggestion = _suggest_profile_name(name)
    return ValueError(
        f"{name!r} is not a valid profile name. {_PROFILE_NAME_RULE} (for example: {suggestion}). "
        f"Then run `hermes profile create {suggestion}`."
    )

def normalize_profile_name(name: str) -> str:
    """Canonical profile id used on disk and in ``-p`` argv: lowercase, ``default`` matched
    case-insensitively. Dashboards/tools may pass title-cased labels — normalize before
    validation, assignment, and subprocess spawn.

    Named profiles are stored lowercase under ``profiles/<id>/``. The special
    alias ``default`` is matched case-insensitively (``Default`` → ``default``).
    Dashboards and tools may pass title-cased display labels; normalize before
    validation, assignment, and subprocess spawn (see issue #18498).

    Raises ``ValueError`` for non-string input: a numeric profile id (e.g. a
    DB row id or a falsy sentinel) silently coerced via ``str()`` becomes a
    real on-disk profile directory (``profiles/0/``, #88842). Callers that
    hold a numeric id must resolve it to an actual profile name first.
    """
    if not isinstance(name, str):
        raise ValueError(
            "profile name must be a string, got "
            f"{type(name).__name__}: {name!r}"
        )
    stripped = name.strip()
    if not stripped:
        raise ValueError("profile name cannot be empty")
    if stripped.casefold() == "default":
        return "default"
    return stripped.lower()

def validate_profile_name(name: str) -> None:
    """Raise ``ValueError`` unless *name* is a valid profile id (strict as-given lowercase —
    normalize mixed-case input first) and not in ``_RESERVED_NAMES``; ``default`` passes.

    Callers that accept mixed-case or title-cased input from users (dashboard UI, CLI args) should call
    :func:`normalize_profile_name` first. This separation keeps validate honest about what the on-disk
    directory name must look like, while ingress-point normalization handles UX flexibility (see #18498).
    """
    if name == "default":
        return  # special alias for ~/.hermes
    if not _PROFILE_ID_RE.match(name):
        raise _invalid_profile_name_error(name)
    if name in _RESERVED_NAMES:
        raise ValueError(
            f"Profile name {name!r} is reserved — it collides with either "
            f"the Hermes installation itself or a common system binary.  "
            f"Pick a different name."
        )

def validate_alias_name(name: str) -> None:
    """Raise ``ValueError`` unless *name* is a safe wrapper filename: it is used verbatim
    under ``~/.local/bin``, so ``../../.bashrc`` must never escape the wrapper dir."""
    if not _PROFILE_ID_RE.match(name):
        raise ValueError(f"Invalid alias name {name!r}. {_PROFILE_NAME_RULE}.")

# Preserve the established public function/pickle paths while their implementation stays a pure leaf.
normalize_profile_name.__module__ = "hermes_cli.profiles"
validate_alias_name.__module__ = "hermes_cli.profiles"
validate_profile_name.__module__ = "hermes_cli.profiles"
