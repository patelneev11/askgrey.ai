from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.services.pdf_extraction import ExtractionTable

MAX_SOURCES = 50
MAX_GOAL_CHARS = 2000


class WorkspaceSource(BaseModel):
    """One paper queued in the tab.

    An uploaded paper survives a reload through `document_id` — the bytes themselves are
    kept server-side — while a linked paper only needs its URL to be re-fetched.
    """

    id: str = Field(min_length=1, max_length=500)
    label: str = Field(min_length=1, max_length=500)
    kind: Literal["upload", "url"]
    url: str = Field(default="", max_length=2000)
    document_id: str = Field(default="", max_length=64)


class WorkspaceWrite(BaseModel):
    goal: str = Field(default="", max_length=MAX_GOAL_CHARS)
    sources: list[WorkspaceSource] = Field(default_factory=list, max_length=MAX_SOURCES)
    table: ExtractionTable | None = None


class WorkspaceRead(WorkspaceWrite):
    updated_at: datetime | None = None
    # Which of the saved documents still have their bytes on the server, so the client knows
    # up front which citations can be rendered as pages rather than as quotes.
    stored_document_ids: list[str] = Field(default_factory=list)
