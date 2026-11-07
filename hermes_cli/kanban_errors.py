"""Business refusals that must not absorb storage/runtime infrastructure failures."""


class TaskAlreadyClaimedError(RuntimeError):
    """Reassignment requires the active task claim to be released first."""
