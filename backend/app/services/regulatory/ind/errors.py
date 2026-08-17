class IndError(Exception):
    """Base class. These messages reach the client, so they never quote submitted data."""


class IndRequestError(IndError):
    """The request cannot be drafted from."""


class IndDrafterError(IndError):
    """The drafter failed or returned something unusable."""


class IndDrafterUnavailableError(IndError):
    """No LLM credentials are configured, so no section can be drafted."""
