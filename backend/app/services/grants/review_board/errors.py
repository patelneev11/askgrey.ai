from app.services.grants.errors import GrantsError


class ReviewBoardConfigError(GrantsError):
    """`personas.json` is missing, malformed, or names a persona that cannot be reviewed with."""


class ReviewBoardError(GrantsError):
    """The model was unreachable, or returned something that is not a usable review."""


class ReviewBoardUnavailableError(ReviewBoardError):
    """No LLM credentials are configured, so no review can be attempted and none is invented."""
