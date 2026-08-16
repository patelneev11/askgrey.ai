class GrantsError(Exception):
    """Base class for every failure raised by the grants service."""


class InvalidQueryError(GrantsError):
    """The caller's filters were empty, contradictory, or rejected by a provider."""


class GrantsRequestError(GrantsError):
    """A provider returned an error status, or was unreachable after all retries."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class GrantsResponseError(GrantsError):
    """A provider returned a payload that could not be parsed."""


class MatchingError(GrantsError):
    """The semantic matcher could not rank the candidate opportunities."""
