"""Exceptions that carry a message the user should see."""


class ParseError(Exception):
    """The expression text is invalid. `position` is a 0-based character index."""

    def __init__(self, message: str, position: int) -> None:
        super().__init__(message)
        self.message = message
        self.position = position


class ApiError(Exception):
    """A request-level problem (unknown preset, ...)."""

    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
