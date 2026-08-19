import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ChatConversation(Base):
    """One chat thread, owned by exactly one account.

    Threads are kept because the chat is the tab that accumulates reasoning about work done in
    the other tabs: losing it on reload would make every answer a one-off.
    """

    __tablename__ = "chat_conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ChatMessage(Base):
    """One turn of a thread: what was said, and which tools ran to say it.

    `trace` is the JSON list of tool steps behind an assistant turn — the same cards the browser
    showed while it streamed — so reopening a thread shows how an answer was reached rather than
    an unsourced paragraph. Tool arguments and result summaries are stored; document contents and
    credentials never reach a step.
    """

    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    conversation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("chat_conversations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    trace: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
