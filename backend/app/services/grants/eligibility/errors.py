from app.services.grants.errors import GrantsError


class EligibilityConfigError(GrantsError):
    """The rules config is missing, malformed, or names a rule with no evaluator behind it."""
