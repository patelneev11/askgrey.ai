from __future__ import annotations

from pydantic import BaseModel


class UnavailableProperty(BaseModel):
    """
    A property a screening service refuses to produce, and what it would take to produce it.

    Modelled explicitly rather than omitted: a missing key reads as an oversight, while an
    entry saying binding affinity needs a target structure and a docking pipeline is the
    honest answer, and the frontend can render it. Shared across the screening services so
    every "we do not compute this" claim in the API has one shape.
    """

    key: str
    label: str
    available: bool = False
    reason: str
    requires: str
