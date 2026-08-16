from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class RecordSource(str, Enum):
    """Which provider a record came from. Rendered as the provenance badge on a review row."""

    PUBMED = "pubmed"
    PUBCHEM = "pubchem"
    CLINICALTRIALS = "clinicaltrials"
    GRANTS = "grants"
    PDF = "pdf"


class SourceRecord(BaseModel):
    """
    The provider-agnostic row every service normalizes into.

    Review tables mix literature and chemistry rows, so each provider keeps its own rich model
    (`Article`, `CompoundRecord`, `TrialRecord`) and additionally projects into this shape:
    identity plus a flat `fields` map of already-formatted cell values. Columns are therefore
    driven by the data rather than hardcoded per source, and every cell keeps a link back to
    its origin.
    """

    source: RecordSource
    record_id: str
    title: str = ""
    subtitle: str = ""
    url: str = ""
    fields: dict[str, str] = Field(default_factory=dict)
