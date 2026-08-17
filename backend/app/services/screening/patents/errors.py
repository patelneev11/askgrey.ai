from ..errors import ScreeningError


class PatentSearchError(ScreeningError):
    """Base class for every failure raised by the patent/IP landscape service."""


class InvalidKeywordError(PatentSearchError):
    """The caller's keyword text was empty, too long, or contained no searchable term."""


class InvalidFilterError(PatentSearchError):
    """The caller's date filter, sort or paging arguments were inconsistent or out of bounds."""


class PatentRequestError(PatentSearchError):
    """The patent search API returned an error status, or was unreachable after all retries."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class PatentResponseError(PatentSearchError):
    """The patent search API returned a payload that could not be parsed."""
