"""Storage failures safe to expose without connection secrets or SQL values."""


class StorageError(RuntimeError):
    """Base for backend-independent persistence failures."""


class StorageConfigurationError(StorageError, ValueError):
    """Invalid backend configuration or missing profile credential."""


class StorageDriverError(StorageError):
    """The optional PostgreSQL stack is unavailable."""


class StorageUnavailableError(StorageError):
    """A connection or bounded pool wait failed."""


class StorageSchemaError(StorageError):
    """The selected schema is absent or incompatible."""


class StorageNotReadyError(StorageError):
    """The PostgreSQL backend cannot yet serve the complete business contract."""


class StorageClosedError(StorageError):
    """A released database handle was used."""
