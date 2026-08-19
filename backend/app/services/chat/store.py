"""
Conversation persistence for the chat tab.

Account-scoped the same way the saved library is: a thread that belongs to somebody else is a
404, indistinguishable from one that never existed, so an id cannot be used to probe another
account. Threads hold what was said and the tool steps behind each answer — never document
bytes, credentials or anything a tool read on the way.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Literal

from pydantic import JsonValue, ValidationError
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models.chat import ChatConversation, ChatMessage
from app.services.chat.models import (
    MAX_TITLE_CHARS,
    ChatMessageRead,
    ChatReference,
    ConversationDetail,
    ConversationSummary,
    ReferenceKind,
    ToolStep,
)
from app.services.library import LibraryRequestError, get_artifact
from app.services.literature import get_workspace
from app.services.protocols import ProtocolRequestError
from app.services.protocols.history import get_protocol

# How much of a thread is replayed to the model. Long enough to hold a working session, short
# enough that an old thread does not turn every reply into an expensive one.
HISTORY_TURNS = 20
MAX_HISTORY_CHARS = 6000
MAX_REFERENCE_CHARS = 20000

Role = Literal["user", "assistant"]


class ChatRequestError(ValueError):
    """The caller asked about a thread or a reference that is not theirs, or does not exist."""


def create_conversation(db: Session, *, user_id: str, title: str = "") -> ConversationSummary:
    record = ChatConversation(user_id=user_id, title=title[:MAX_TITLE_CHARS])
    db.add(record)
    db.commit()
    db.refresh(record)
    return _summary(record, message_count=0)


def list_conversations(db: Session, *, user_id: str) -> list[ConversationSummary]:
    counted = db.execute(
        select(ChatMessage.conversation_id, func.count(ChatMessage.id))
        .join(ChatConversation, ChatConversation.id == ChatMessage.conversation_id)
        .where(ChatConversation.user_id == user_id)
        .group_by(ChatMessage.conversation_id)
    ).all()
    counts: dict[str, int] = {row[0]: row[1] for row in counted}
    records = db.scalars(
        select(ChatConversation)
        .where(ChatConversation.user_id == user_id)
        .order_by(ChatConversation.updated_at.desc())
    ).all()
    return [_summary(record, message_count=counts.get(record.id, 0)) for record in records]


def get_conversation(db: Session, *, conversation_id: str, user_id: str) -> ConversationDetail:
    record = _owned(db, conversation_id=conversation_id, user_id=user_id)
    messages = _messages(db, conversation_id=record.id)
    summary = _summary(record, message_count=len(messages))
    return ConversationDetail(**summary.model_dump(), messages=messages)


def delete_conversation(db: Session, *, conversation_id: str, user_id: str) -> None:
    record = _owned(db, conversation_id=conversation_id, user_id=user_id)
    db.execute(delete(ChatMessage).where(ChatMessage.conversation_id == record.id))
    db.delete(record)
    db.commit()


def append_message(
    db: Session,
    *,
    conversation_id: str,
    user_id: str,
    role: Role,
    text: str,
    steps: tuple[ToolStep, ...] = (),
) -> ChatMessageRead:
    record = _owned(db, conversation_id=conversation_id, user_id=user_id)
    next_sequence = (
        db.scalar(
            select(func.max(ChatMessage.sequence)).where(ChatMessage.conversation_id == record.id)
        )
        or 0
    ) + 1
    message = ChatMessage(
        conversation_id=record.id,
        role=role,
        text=text,
        trace=json.dumps([step.model_dump(mode="json") for step in steps]),
        sequence=next_sequence,
    )
    db.add(message)
    # A thread named after its first question is findable in a list; an untitled one is not.
    if role == "user" and not record.title.strip():
        record.title = text.strip()[:MAX_TITLE_CHARS]
    record.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(message)
    return _read(message)


def history_for_model(
    db: Session, *, conversation_id: str, user_id: str
) -> list[dict[str, object]]:
    """The thread as Messages API turns.

    Only the prose is replayed, not the tool blocks: a tool result is re-derivable and replaying
    every one of them would make each turn cost more than the last for no extra fidelity. The
    steps stay in the trace for the researcher.
    """
    _owned(db, conversation_id=conversation_id, user_id=user_id)
    messages = _messages(db, conversation_id=conversation_id)[-HISTORY_TURNS:]
    turns: list[dict[str, object]] = []
    for message in messages:
        text = message.text.strip()
        if not text:
            continue
        turns.append({"role": message.role, "content": text[:MAX_HISTORY_CHARS]})
    return turns


def resolve_references(db: Session, *, user_id: str, references: list[ChatReference]) -> str:
    """Render the caller's @-referenced work as a context block.

    Resolved server-side under the caller's own id: a reference is the researcher naming their
    own artifact, never a way to hand the model an id it was not entitled to read.
    """
    blocks: list[str] = []
    for reference in references:
        blocks.append(_reference_block(db, user_id=user_id, reference=reference))
    if not blocks:
        return ""
    joined = "\n\n".join(blocks)[:MAX_REFERENCE_CHARS]
    return (
        "The researcher attached the following work of their own. Treat it as context they "
        f"already have, and keep any caveat it carries:\n\n{joined}"
    )


def _reference_block(db: Session, *, user_id: str, reference: ChatReference) -> str:
    if reference.kind is ReferenceKind.LITERATURE_WORKSPACE:
        workspace = get_workspace(db, user_id)
        return f"Literature workspace:\n{_json(workspace.model_dump(mode='json'))}"
    if reference.kind is ReferenceKind.SAVED_WORK:
        try:
            artifact = get_artifact(db, artifact_id=reference.id, user_id=user_id)
        except LibraryRequestError as exc:
            raise ChatRequestError(str(exc)) from exc
        return (
            f"Saved {artifact.kind} — {artifact.title}:\n{_json(artifact.model_dump(mode='json'))}"
        )
    try:
        protocol = get_protocol(db, protocol_id=reference.id, user_id=user_id)
    except ProtocolRequestError as exc:
        raise ChatRequestError(str(exc)) from exc
    return (
        f"Saved protocol — {protocol.protocol.title} (version {protocol.version}):\n"
        f"{_json(protocol.model_dump(mode='json'))}"
    )


def _json(payload: JsonValue) -> str:
    return json.dumps(payload, separators=(",", ":"))


def _owned(db: Session, *, conversation_id: str, user_id: str) -> ChatConversation:
    record = db.get(ChatConversation, conversation_id)
    if record is None or record.user_id != user_id:
        raise ChatRequestError("no conversation with that id")
    return record


def _messages(db: Session, *, conversation_id: str) -> list[ChatMessageRead]:
    records = db.scalars(
        select(ChatMessage)
        .where(ChatMessage.conversation_id == conversation_id)
        .order_by(ChatMessage.sequence)
    ).all()
    return [_read(record) for record in records]


def _read(record: ChatMessage) -> ChatMessageRead:
    return ChatMessageRead(
        id=record.id,
        role="assistant" if record.role == "assistant" else "user",
        text=record.text,
        steps=_steps(record.trace),
        created_at=record.created_at,
    )


def _steps(trace: str) -> list[ToolStep]:
    """A trace that no longer parses loses its cards, not the answer above them."""
    try:
        parsed = json.loads(trace)
    except ValueError:
        return []
    if not isinstance(parsed, list):
        return []
    steps: list[ToolStep] = []
    for entry in parsed:
        try:
            steps.append(ToolStep.model_validate(entry))
        except ValidationError:
            continue
    return steps


def _summary(record: ChatConversation, *, message_count: int) -> ConversationSummary:
    return ConversationSummary(
        id=record.id,
        title=record.title,
        message_count=message_count,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )
