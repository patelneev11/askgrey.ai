class ScreeningError(Exception):
    """Base class for every failure raised by the screening services."""


class InvalidStructureError(ScreeningError):
    """The caller's structure was empty, too long, or could not be parsed as SMILES."""


class SuggestionError(ScreeningError):
    """The substituent suggester could not produce usable output."""
