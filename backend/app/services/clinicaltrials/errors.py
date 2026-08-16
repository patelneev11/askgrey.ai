class ClinicalTrialsError(Exception):
    """Base class for every failure raised by the ClinicalTrials.gov service."""


class InvalidQueryError(ClinicalTrialsError):
    """The caller's filters were empty, contradictory, or rejected by the API as unparseable."""


class ClinicalTrialsRequestError(ClinicalTrialsError):
    """The API returned an error status, or was unreachable after all retries."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class ClinicalTrialsResponseError(ClinicalTrialsError):
    """The API returned a payload that could not be parsed."""
