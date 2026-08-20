"""Wire shapes for the chat tab: requests, stored turns, and the events the stream carries."""

from __future__ import annotations

import json
from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, JsonValue, model_validator

MAX_MESSAGE_CHARS = 8000
MAX_REFERENCES = 10
MAX_TITLE_CHARS = 200


class ReferenceKind(str, Enum):
    """What a researcher can point the chat at. Everything here is their own account's work."""

    __str__ = str.__str__

    SAVED_WORK = "saved_work"
    PROTOCOL = "protocol"
    LITERATURE_WORKSPACE = "literature_workspace"


class ChatReference(BaseModel):
    """An @-reference to something already saved in another tab.

    The workspace is a singleton per account, so it carries no id; the other kinds are looked up
    under the calling account and are a 422 if they belong to somebody else.
    """

    kind: ReferenceKind
    id: str = Field(default="", max_length=64)

    @model_validator(mode="after")
    def _id_matches_kind(self) -> ChatReference:
        if self.kind is not ReferenceKind.LITERATURE_WORKSPACE and not self.id:
            raise ValueError(f"a {self.kind} reference needs an id")
        return self


class Citation(BaseModel):
    """Where a tool result came from, so an answer can be checked rather than believed."""

    label: str
    source: str
    identifier: str = ""
    url: str = ""


class ToolStep(BaseModel):
    """One tool the model asked for and what came back, as the trace shows it.

    `detail` is the tool's own response, bounded before it is stored: enough to render a card,
    never a whole paper.
    """

    id: str
    tool: str
    title: str
    arguments: dict[str, JsonValue] = Field(default_factory=dict)
    ok: bool = True
    summary: str = ""
    citations: list[Citation] = Field(default_factory=list)
    detail: JsonValue = None


class ChatMessageRead(BaseModel):
    id: str
    role: Literal["user", "assistant"]
    text: str
    steps: list[ToolStep] = Field(default_factory=list)
    created_at: datetime


class ConversationSummary(BaseModel):
    id: str
    title: str
    message_count: int
    created_at: datetime
    updated_at: datetime


class ConversationDetail(ConversationSummary):
    messages: list[ChatMessageRead] = Field(default_factory=list)


class CreateConversationRequest(BaseModel):
    title: str = Field(default="", max_length=MAX_TITLE_CHARS)


class SendMessageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)
    references: list[ChatReference] = Field(default_factory=list, max_length=MAX_REFERENCES)


class ToolSummary(BaseModel):
    """A tool as the tab lists it, so the UI can say what the chat is able to do."""

    name: str
    title: str
    description: str
    tab: str


class AssistantLimits(BaseModel):
    """The rules the tab has to show: what the assistant answers, and what is left to spend.

    Caps are USD per account. A cap of 0 means it is not enforced, which the tab renders as "no
    cap" rather than as an exhausted budget.
    """

    scope_version: str
    scope_purpose: str
    scope_refusal: str
    daily_spent_usd: float
    daily_cap_usd: float
    monthly_spent_usd: float
    monthly_cap_usd: float
    exhausted_cap: Literal["", "daily", "monthly"]
    max_tool_steps: int
    max_message_chars: int


class TextEvent(BaseModel):
    type: Literal["text"] = "text"
    text: str


class ToolStartEvent(BaseModel):
    type: Literal["tool_start"] = "tool_start"
    id: str
    tool: str
    title: str
    arguments: dict[str, JsonValue] = Field(default_factory=dict)


class ToolResultEvent(BaseModel):
    type: Literal["tool_result"] = "tool_result"
    step: ToolStep


class NoticeEvent(BaseModel):
    """Something the researcher needs told about the answer itself, e.g. that it was cut short."""

    type: Literal["notice"] = "notice"
    message: str


class DoneEvent(BaseModel):
    type: Literal["done"] = "done"
    conversation_id: str
    message_id: str


class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    message: str


ChatEvent = TextEvent | ToolStartEvent | ToolResultEvent | NoticeEvent | DoneEvent | ErrorEvent


def encode_event(event: ChatEvent) -> str:
    """One server-sent event. Newlines in prose would end the frame, so the payload is JSON."""
    return f"data: {json.dumps(event.model_dump(mode='json'))}\n\n"
