class EnglishNotesError(Exception):
    """An error that can be safely handled at an application boundary."""


class StorageError(EnglishNotesError):
    """The local database cannot complete the operation."""


class NotFoundError(EnglishNotesError):
    """The requested active lesson or note does not exist."""


class ConflictError(EnglishNotesError):
    """The record changed since it was read; do not silently overwrite it."""


class ValidationError(EnglishNotesError):
    """Invalid user input."""
