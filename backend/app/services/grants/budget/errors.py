from app.services.grants.errors import GrantsError


class BudgetError(GrantsError):
    """Base class for every failure raised while building a budget."""


class BudgetConfigError(BudgetError):
    """The budget rules config is missing, malformed, or internally inconsistent."""


class BudgetInputError(BudgetError):
    """The requested budget cannot be costed as described."""
