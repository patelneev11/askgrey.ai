from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from app.core.llm_cost import get_meter
from app.services.llm import AnthropicError, AnthropicMessagesClient

pytestmark = pytest.mark.asyncio

Handler = Callable[[httpx.Request], httpx.Response]


def client(handler: Handler, **kwargs: object) -> AnthropicMessagesClient:
    return AnthropicMessagesClient(
        api_key="key",
        model="claude-sonnet-4-5",
        max_tokens=256,
        timeout=5.0,
        transport=httpx.MockTransport(handler),
        **kwargs,  # type: ignore[arg-type]
    )


def text_reply(text: str) -> Handler:
    return lambda _request: httpx.Response(200, json={"content": [{"type": "text", "text": text}]})


async def test_sends_the_prefill_as_an_assistant_turn_and_joins_text_blocks() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.headers))
        seen["body"] = request.read().decode()
        return httpx.Response(
            200,
            json={"content": [{"type": "text", "text": '"a": 1,'}, {"type": "text", "text": "}"}]},
        )

    completion = await client(handler).complete(system="be terse", prompt="hello", prefill="{")

    assert completion == '"a": 1,}'
    assert seen["x-api-key"] == "key"
    assert seen["anthropic-version"] == "2023-06-01"
    body = str(seen["body"])
    assert '{"role":"assistant","content":"{"}' in body
    assert '"temperature":0' in body


async def test_omits_the_assistant_turn_when_no_prefill_is_requested() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "assistant" not in request.read().decode()
        return httpx.Response(200, json={"content": [{"type": "text", "text": "ok"}]})

    assert await client(handler).complete(system="s", prompt="p") == "ok"


@pytest.mark.parametrize(
    ("handler", "message"),
    [
        (lambda _request: httpx.Response(529, json={}), "Claude returned HTTP 529"),
        (lambda _request: httpx.Response(200, json={"unexpected": True}), "unexpected shape"),
        (text_reply("   "), "no text content"),
    ],
)
async def test_surfaces_unusable_replies_as_anthropic_errors(
    handler: Handler, message: str
) -> None:
    with pytest.raises(AnthropicError, match=message):
        await client(handler).complete(system="s", prompt="p")


async def test_reports_a_transport_failure_rather_than_leaking_httpx() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(AnthropicError, match="Claude request failed"):
        await client(handler).complete(system="s", prompt="p")


async def test_rejects_an_empty_api_key_at_construction() -> None:
    with pytest.raises(ValueError, match="api_key is required"):
        AnthropicMessagesClient(api_key="", model="m", max_tokens=1, timeout=1.0)


async def test_meters_the_tokens_the_api_reports_against_the_calling_feature() -> None:
    meter = get_meter()
    meter.reset()

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": "ok"}],
                "usage": {"input_tokens": 1200, "output_tokens": 300},
            },
        )

    await client(handler, purpose="pdf_extraction").complete(system="s", prompt="p")

    usage = meter.snapshot()
    assert (usage.calls, usage.input_tokens, usage.output_tokens) == (1, 1200, 300)
    meter.reset()


async def test_a_reply_without_a_usage_block_still_counts_as_a_call() -> None:
    meter = get_meter()
    meter.reset()

    await client(text_reply("ok")).complete(system="s", prompt="p")

    # Dropping it would make the call count, not just the cost, understate reality.
    assert meter.snapshot().calls == 1
    meter.reset()
