"""Storage failures safe to expose without connection secrets or SQL values."""


class StorageError(RuntimeError):
    """Base for backend-independent persistence failures."""


class StorageConfigurationError(StorageError, ValueError):
    """Invalid backend configuration or missing profile credential."""


class StorageDriverError(StorageError):
    """The optional PostgreSQL stack is unavailable."""


class StorageUnavailableError(StorageError):
    """A connection or bounded pool wait failed."""


class StorageQueryTimeoutError(StorageUnavailableError, TimeoutError):
    """The backend cancelled a read at its configured deadline."""


class StorageSchemaError(StorageError):
    """The selected schema is absent or incompatible."""


class StorageNotReadyError(StorageError):
    """The PostgreSQL backend cannot yet serve the complete business contract."""


class StorageClosedError(StorageError):
    """A released database handle was used."""


class StorageWriteError(StorageError):
    """A write transaction failed and was rolled back."""


class StorageConflictError(StorageWriteError):
    """A database constraint refused the operation."""


class RetryableStorageError(StorageWriteError):
    """PostgreSQL confirmed a serialization/deadlock rollback."""


class StorageBusyError(StorageWriteError):
    """A bounded lock wait failed in the transaction body and rolled back."""


class UnknownCommitError(StorageError):
    """The client cannot determine whether COMMIT reached the server."""
