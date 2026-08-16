from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field

# The one sentence that must travel with every drafted protocol, in the API payload as well as
# the UI, so no consumer can render a draft without the review requirement attached.
REVIEW_DISCLAIMER = "Agent-drafted content. Requires qualified researcher review before lab use."

MAX_STEPS = 60
MAX_MATERIALS = 60


class DraftOrigin(str, Enum):
    """Where the content came from. `agent_drafted` is never validated by anything here."""

    AGENT_DRAFTED = "agent_drafted"
    RESEARCHER_EDITED = "researcher_edited"


class ProtocolMaterial(BaseModel):
    """A material or reagent line. Amounts are the model's words, not computed values."""

    name: str = Field(min_length=1, max_length=200)
    amount: str = Field(default="", max_length=120)
    vendor_or_catalog: str = Field(default="", max_length=200)
    storage: str = Field(default="", max_length=120)
    note: str = Field(default="", max_length=400)


class ProtocolStep(BaseModel):
    """
    One discrete, orderable step.

    Steps are separate records rather than one text blob so the frontend can render, edit and
    reorder them individually, and so a calculator field can be attached to a single step by id.
    """

    id: str = Field(min_length=1, max_length=100)
    order: int = Field(ge=1, le=MAX_STEPS)
    title: str = Field(min_length=1, max_length=200)
    instruction: str = Field(min_length=1, max_length=4000)
    duration: str = Field(default="", max_length=120)
    temperature: str = Field(default="", max_length=120)
    equipment: list[str] = Field(default_factory=list, max_length=12)
    critical_note: str = Field(default="", max_length=600)


class ProtocolDraft(BaseModel):
    """
    A drafted protocol: materials, ordered steps, timing and expected outcomes.

    `origin` and `disclaimer` are part of the payload rather than presentation state. Scientific
    correctness is not asserted anywhere in this model — only that the structure is complete.
    """

    title: str = Field(min_length=1, max_length=300)
    goal: str = Field(min_length=1, max_length=2000)
    assay_type: str = Field(default="", max_length=200)
    summary: str = Field(default="", max_length=2000)
    materials: list[ProtocolMaterial] = Field(default_factory=list, max_length=MAX_MATERIALS)
    steps: list[ProtocolStep] = Field(min_length=1, max_length=MAX_STEPS)
    total_duration: str = Field(default="", max_length=200)
    expected_outcomes: list[str] = Field(default_factory=list, max_length=12)
    origin: DraftOrigin = DraftOrigin.AGENT_DRAFTED
    disclaimer: str = REVIEW_DISCLAIMER
    model: str = Field(default="", max_length=100)
    drafted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DraftRequest(BaseModel):
    """A natural-language experimental goal, bounded in length."""

    goal: str = Field(min_length=10, max_length=2000)
    organism_or_sample: str = Field(default="", max_length=200)
    notes: str = Field(default="", max_length=1000)
