class MemoryError(Exception):
    """A bounded public error code, never an upstream exception message."""
    status = 503

    def __init__(self, code="memory_unavailable"):
        self.code = code
        super().__init__(code)


class Conflict(MemoryError):
    status = 409


class PayloadTooLarge(MemoryError):
    status = 413
