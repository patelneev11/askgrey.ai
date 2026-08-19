import logging
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Response, status
from fastapi.responses import StreamingResponse

from app.api.deps import ClientIp, DbSession, LlmUser, ThrottledUser
from app.core import audit
from app.core.config import get_settings
from app.services.chat.agent import ChatAgent
from app.services.chat.models import (
    ConversationDetail,
    ConversationSummary,
    CreateConversationRequest,
    ErrorEvent,
    SendMessageRequest,
    ToolSummary,
    encode_event,
)
from app.services.chat.store import (
    ChatRequestError,
    append_message,
    create_conversation,
    delete_conversation,
    get_conversation,
    history_for_model,
    list_conversations,
    resolve_references,
)
from app.services.chat.tools import TOOLS, ToolContext, ToolRegistry
from app.services.llm.tool_use import AnthropicToolClient

router = APIRouter(prefix="/chat", tags=["chat"])

logger = logging.getLogger("askgrey.chat")

ConversationId = Annotated[str, Path(min_length=1, max_length=36)]


def get_chat_agent() -> ChatAgent:
    """A turn's agent, with its own Claude client.

    Built per request because the client owns a connection and is closed when the turn ends.
    Without a key the tab is unavailable rather than silently degraded: unlike query translation,
    there is no rule-based fallback that could answer a research question.
    """
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "the assistant needs ANTHROPIC_API_KEY configured on the server",
        )
    client = AnthropicToolClient(
        api_key=settings.anthropic_api_key,
        model=settings.llm_model,
        base_url=settings.anthropic_base_url,
        anthropic_version=settings.anthropic_version,
        max_tokens=settings.chat_max_tokens,
        timeout=settings.chat_timeout_seconds,
        purpose="chat",
    )
    return ChatAgent(
        client=client,
        registry=ToolRegistry(),
        max_steps=settings.chat_max_tool_steps,
    )


Agent = Annotated[ChatAgent, Depends(get_chat_agent)]


@router.get("/tools", response_model=list[ToolSummary])
def list_chat_tools(_user: ThrottledUser) -> list[ToolSummary]:
    """What the assistant can actually do, so the tab can say so instead of implying anything."""
    return [
        ToolSummary(name=tool.name, title=tool.title, description=tool.description, tab=tool.tab)
        for tool in TOOLS
    ]


@router.post(
    "/conversations", response_model=ConversationSummary, status_code=status.HTTP_201_CREATED
)
def start_conversation(
    request: CreateConversationRequest, db: DbSession, user: ThrottledUser
) -> ConversationSummary:
    return create_conversation(db, user_id=str(user.id), title=request.title)


@router.get("/conversations", response_model=list[ConversationSummary])
def read_conversations(db: DbSession, user: ThrottledUser) -> list[ConversationSummary]:
    return list_conversations(db, user_id=str(user.id))


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
def read_conversation(
    conversation_id: ConversationId, db: DbSession, user: ThrottledUser
) -> ConversationDetail:
    try:
        return get_conversation(db, conversation_id=conversation_id, user_id=str(user.id))
    except ChatRequestError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_conversation(
    conversation_id: ConversationId, db: DbSession, user: ThrottledUser, ip: ClientIp
) -> Response:
    try:
        delete_conversation(db, conversation_id=conversation_id, user_id=str(user.id))
    except ChatRequestError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    audit.record(
        "chat.conversation_deleted",
        actor=str(user.id),
        client_ip=ip,
        detail={"conversation_id": conversation_id},
        db=db,
        user_id=str(user.id),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/conversations/{conversation_id}/messages")
async def send_message(
    conversation_id: ConversationId,
    request: SendMessageRequest,
    db: DbSession,
    user: LlmUser,
    ip: ClientIp,
    agent: Agent,
) -> StreamingResponse:
    """
    Answer one message, streaming the reply and the tool steps behind it.

    On the LLM limiter and the daily call budget, like every other endpoint that spends money at
    Anthropic. The message is stored before the model runs, so a failed turn still shows what was
    asked rather than losing it.
    """
    user_id = str(user.id)
    try:
        reference_context = resolve_references(db, user_id=user_id, references=request.references)
    except ChatRequestError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    try:
        append_message(
            db,
            conversation_id=conversation_id,
            user_id=user_id,
            role="user",
            text=request.message,
        )
    except ChatRequestError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    history = history_for_model(db, conversation_id=conversation_id, user_id=user_id)
    audit.record(
        "chat.message_sent",
        actor=user_id,
        client_ip=ip,
        detail={
            "conversation_id": conversation_id,
            "message_chars": len(request.message),
            "references": len(request.references),
        },
        db=db,
        user_id=user_id,
    )

    context = ToolContext(db=db, user_id=user_id)

    async def stream() -> AsyncIterator[str]:
        try:
            async for event in agent.run(
                context=context,
                conversation_id=conversation_id,
                history=history,
                reference_context=reference_context,
                client_ip=ip,
            ):
                yield encode_event(event)
        except Exception:
            # The status line is long gone by the time a turn breaks, so the failure has to be
            # delivered inside the stream or the tab would sit on a half-written answer. Logged
            # with a stack trace; the client is told only that the turn failed.
            logger.exception("chat turn failed", extra={"conversation_id": conversation_id})
            yield encode_event(ErrorEvent(message="the assistant stopped unexpectedly; try again"))

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-store",
            # Proxies that buffer would hold the whole answer back and defeat the streaming.
            "X-Accel-Buffering": "no",
        },
    )
