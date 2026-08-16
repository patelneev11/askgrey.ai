class ProtocolError(Exception):
    """Base class for protocol drafting and review failures."""


class ProtocolRequestError(ProtocolError):
    """The request is well-formed but cannot be served (empty goal, unusable protocol)."""


class DrafterUnavailableError(ProtocolError):
    """No model is configured, so no draft can be produced.

    Nothing is invented in this case: a protocol nobody drafted must not be returned as one
    that somebody did.
    """


class DrafterError(ProtocolError):
    """The model was reached but did not return a usable protocol."""
