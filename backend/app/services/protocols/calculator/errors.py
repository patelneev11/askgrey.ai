class CalculatorError(Exception):
    """Base class for every failure raised by the bench calculator."""


class UnitError(CalculatorError, ValueError):
    """
    A unit string could not be parsed.

    Also a `ValueError` so that a bad unit inside a request body surfaces as a Pydantic
    validation error (HTTP 422) rather than an unhandled exception.
    """


class UnitMismatchError(CalculatorError):
    """
    Two quantities that must be comparable are measured in different families.

    Converting mM to M is arithmetic; converting mg/mL to M needs a molecular weight, and
    converting a fold stock (100x) to either is not defined at all. Rather than guess a
    conversion, the calculator refuses — a silently wrong unit conversion is the most likely
    way this code could put a wrong volume on a bench.
    """


class CalculatorInputError(CalculatorError):
    """The inputs are individually valid but cannot produce an answer (zero divisor, no unknown)."""
