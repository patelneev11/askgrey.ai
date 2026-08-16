class PubMedError(Exception):
    """Base class for every failure raised by the PubMed service."""


class InvalidQueryError(PubMedError):
    """The caller's natural-language query was empty, too long, or otherwise unusable."""


class TranslationError(PubMedError):
    """The natural-language query could not be turned into Entrez syntax."""


class EntrezRequestError(PubMedError):
    """NCBI returned an error status, or was unreachable after all retries."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class EntrezResponseError(PubMedError):
    """NCBI returned a payload that could not be parsed."""
