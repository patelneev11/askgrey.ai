class PubChemError(Exception):
    """Base class for every failure raised by the PubChem service."""


class InvalidIdentifierError(PubChemError):
    """The caller's identifier was empty, too long, or rejected by PubChem as unparseable."""


class CompoundNotFoundError(PubChemError):
    """PubChem has no compound matching the identifier."""


class PubChemRequestError(PubChemError):
    """PUG-REST returned an error status, or was unreachable after all retries."""

    def __init__(self, message: str, status_code: int | None = None, code: str = "") -> None:
        super().__init__(message)
        self.status_code = status_code
        # PUG-REST fault code, e.g. `PUGREST.NotFound` or `PUGREST.BadRequest`.
        self.code = code


class PubChemResponseError(PubChemError):
    """PUG-REST returned a payload that could not be parsed."""
