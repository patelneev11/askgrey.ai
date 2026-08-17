class PreclinicalError(Exception):
    """Base class. Messages here are shown to the client, so they never quote study data."""


class PreclinicalRequestError(PreclinicalError):
    """The submitted study table cannot be drafted from."""


class DrafterError(PreclinicalError):
    """The narrative drafter failed or returned something unusable."""


class DrafterUnavailableError(PreclinicalError):
    """No LLM credentials are configured, so no narrative can be drafted."""
