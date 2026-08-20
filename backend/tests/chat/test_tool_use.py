"""The streaming Messages client: a turn is only usable if its blocks reassemble exactly.

Text arrives as deltas and tool arguments as JSON fragments, so these tests stream the byte
shapes the API really sends, including the ones that are supposed to fail.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.core.llm_cost import get_meter
from app.services.llm.anthropic import AnthropicError
from app.services.llm.tool_use import (
    AnthropicToolClient,
    TextChunk,
    ToolDefinition,
    TurnComplete,
)

SEARCH = ToolDefinition(
    name="search_pubmed",
    description="Search PubMed.",
    input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
)


def sse(*events: dict[str, object]) -> bytes:
    return b"".join(
        f"event: {event['type']}\ndata: {json.dumps(event)}\n\n".encode() for event in events
    )


def client(
    body: bytes, *, status: int = 200, captured: list[httpx.Request] | None = None
) -> AnthropicToolClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if captured is not None:
            captured.append(request)
        return httpx.Response(status, content=body, headers={"content-type": "text/event-stream"})

    return AnthropicToolClient(
        api_key="test-key",
        model="claude-sonnet-4-5",
        max_tokens=64,
        timeout=5.0,
        transport=httpx.MockTransport(handler),
    )


async def collect(
    stream: AnthropicToolClient, tools: list[ToolDefinition] | None = None
) -> list[object]:
    events: list[object] = []
    async for event in stream.stream_turn(
        system="s",
        messages=[{"role": "user", "content": "hi"}],
        tools=tools or [],
    ):
        events.append(event)
    return events


TEXT_TURN = sse(
    {"type": "message_start", "message": {"usage": {"input_tokens": 11, "output_tokens": 0}}},
    {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
    {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Two "}},
    {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "trials."}},
    {"type": "content_block_stop", "index": 0},
    {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 7}},
    {"type": "message_stop"},
)

TOOL_TURN = sse(
    {"type": "message_start", "message": {"usage": {"input_tokens": 20, "output_tokens": 0}}},
    {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
    {
        "type": "content_block_delta",
        "index": 0,
        "delta": {"type": "text_delta", "text": "Looking."},
    },
    {"type": "content_block_stop", "index": 0},
    {
        "type": "content_block_start",
        "index": 1,
        "content_block": {"type": "tool_use", "id": "toolu_1", "name": "search_pubmed"},
    },
    {
        "type": "content_block_delta",
        "index": 1,
        "delta": {"type": "input_json_delta", "partial_json": '{"query": "GLP'},
    },
    {
        "type": "content_block_delta",
        "index": 1,
        "delta": {"type": "input_json_delta", "partial_json": '-1 obesity"}'},
    },
    {"type": "content_block_stop", "index": 1},
    {"type": "message_delta", "delta": {"stop_reason": "tool_use"}, "usage": {"output_tokens": 31}},
)


@pytest.mark.asyncio
async def test_text_deltas_stream_then_the_turn_closes() -> None:
    events = await collect(client(TEXT_TURN))

    assert [event.text for event in events if isinstance(event, TextChunk)] == ["Two ", "trials."]
    turn = events[-1]
    assert isinstance(turn, TurnComplete)
    assert turn.text == "Two trials."
    assert turn.tools == ()
    assert turn.stop_reason == "end_turn"


@pytest.mark.asyncio
async def test_tool_arguments_reassemble_from_their_fragments() -> None:
    events = await collect(client(TOOL_TURN), tools=[SEARCH])

    turn = events[-1]
    assert isinstance(turn, TurnComplete)
    assert turn.stop_reason == "tool_use"
    assert len(turn.tools) == 1
    assert turn.tools[0].id == "toolu_1"
    assert turn.tools[0].name == "search_pubmed"
    assert turn.tools[0].arguments == {"query": "GLP-1 obesity"}


@pytest.mark.asyncio
async def test_tools_and_the_key_are_sent_but_the_key_is_never_in_the_body() -> None:
    captured: list[httpx.Request] = []

    await collect(client(TOOL_TURN, captured=captured), tools=[SEARCH])

    request = captured[0]
    assert request.headers["x-api-key"] == "test-key"
    body = json.loads(request.content)
    assert body["stream"] is True
    assert body["tools"][0]["name"] == "search_pubmed"
    assert "test-key" not in request.content.decode()


@pytest.mark.asyncio
async def test_reported_usage_is_metered_under_the_chat_purpose() -> None:
    get_meter().reset()

    await collect(client(TEXT_TURN))

    snapshot = get_meter().snapshot()
    assert snapshot.input_tokens == 11
    assert snapshot.output_tokens == 7
    assert snapshot.calls == 1


@pytest.mark.asyncio
async def test_a_stream_error_event_fails_the_turn() -> None:
    body = sse(
        {"type": "message_start", "message": {"usage": {"input_tokens": 5}}},
        {"type": "error", "error": {"type": "overloaded_error"}},
    )

    with pytest.raises(AnthropicError, match="overloaded_error"):
        await collect(client(body))


@pytest.mark.asyncio
async def test_unparseable_tool_arguments_fail_rather_than_reaching_a_tool() -> None:
    body = sse(
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "tool_use", "id": "toolu_2", "name": "search_pubmed"},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "input_json_delta", "partial_json": '{"query": '},
        },
        {"type": "content_block_stop", "index": 0},
    )

    with pytest.raises(AnthropicError, match="unusable arguments"):
        await collect(client(body), tools=[SEARCH])


@pytest.mark.asyncio
async def test_an_http_error_does_not_leak_the_response_body() -> None:
    body = b'{"error": {"message": "account org-1234 is out of credit"}}'

    with pytest.raises(AnthropicError) as raised:
        await collect(client(body, status=429))

    assert "429" in str(raised.value)
    assert "org-1234" not in str(raised.value)


@pytest.mark.asyncio
async def test_a_malformed_stream_line_fails_the_turn() -> None:
    with pytest.raises(AnthropicError, match="unparseable stream event"):
        await collect(client(b"data: {not json}\n\n"))
