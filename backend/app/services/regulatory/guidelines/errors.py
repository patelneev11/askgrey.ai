class GuidelineError(Exception):
    """Base for the guideline checker."""


class GuidelineConfigError(GuidelineError):
    """A shipped reference dataset is missing, malformed, or self-inconsistent."""


class GuidelineInputError(GuidelineError):
    """The section id or draft text cannot be checked as given."""
