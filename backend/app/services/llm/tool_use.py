"""
Streaming, tool-using Messages API turns.

`AnthropicMessagesClient` covers the single-shot "prompt in, text out" call every service tab
makes. The chat tab needs the other two halves of the same API: tools the model may ask us to
run, and token-by-token delivery, because a chat that appears after twenty silent seconds reads
as broken. Both live here rather than in the shared client so the simple path stays simple, and
both report their tokens to the same meter, so chat spend shows up in the existing cost log.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from dataclasses import dataclass

import httpx
from pydantic import JsonValue, TypeAdapter, ValidationError

from app.core.dependency_health import MonitoredAsyncClient
from app.core.llm_cost import get_meter
from app.services.llm.anthropic import (
    DEFAULT_ANTHROPIC_VERSION,
    DEFAULT_BASE_URL,
    AnthropicError,
)

# A tool result is JSON we hand back to the model; the argument shapes it sends us are the same.
JsonDict = dict[str, object]

# Tool arguments arrive as a JSON fragment stream, so they are validated before anything reads
# them as a mapping.
_ARGUMENTS = TypeAdapter(dict[str, JsonValue])


@dataclass(frozen=True)
class ToolDefinition:
    """One tool as the Messages API declares it: a name, a purpose, and a JSON schema."""

    name: str
    description: str
    input_schema: Mapping[str, object]

    def as_payload(self) -> JsonDict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": dict(self.input_schema),
        }


@dataclass(frozen=True)
class ToolInvocation:
    """A `tool_use` block the model emitted, with its arguments already parsed."""

    id: str
    name: str
    arguments: dict[str, JsonValue]


@dataclass(frozen=True)
class TextChunk:
    """Prose to forward to the browser as it arrives."""

    text: str


@dataclass(frozen=True)
class TurnComplete:
    """The end of one assistant turn: what it said, and what it wants run before continuing."""

    text: str
    tools: tuple[ToolInvocation, ...]
    stop_reason: str


TurnEvent = TextChunk | TurnComplete


class _Accumulator:
    """Reassembles the streamed blocks of one turn.

    Text arrives as deltas and tool arguments arrive as JSON fragments, so neither is usable
    until its block closes. Tracked per block index because the two interleave.
    """

    def __init__(self) -> None:
        self.text_parts: list[str] = []
        self.tools: list[ToolInvocation] = []
        self.stop_reason = ""
        self.input_tokens = 0
        self.output_tokens = 0
        self._pending: dict[int, tuple[str, str]] = {}
        self._arguments: dict[int, list[str]] = {}

    def consume(self, event: JsonDict) -> str | None:
        """Fold one SSE event in, returning any text that should be forwarded now."""
        kind = event.get("type")
        if kind == "error":
            raise AnthropicError(f"Claude reported a stream error: {_error_message(event)}")
        if kind == "message_start":
            self._read_usage(event.get("message"))
            return None
        if kind == "content_block_start":
            self._start_block(event)
            return None
        if kind == "content_block_delta":
            return self._delta(event)
        if kind == "content_block_stop":
            self._close_block(event)
            return None
        if kind == "message_delta":
            delta = event.get("delta")
            if isinstance(delta, dict) and isinstance(delta.get("stop_reason"), str):
                self.stop_reason = delta["stop_reason"]
            self._read_usage(event)
            return None
        return None

    def _start_block(self, event: JsonDict) -> None:
        index = event.get("index")
        block = event.get("content_block")
        if not isinstance(index, int) or not isinstance(block, dict):
            return
        if block.get("type") != "tool_use":
            return
        tool_id = block.get("id")
        name = block.get("name")
        if not isinstance(tool_id, str) or not isinstance(name, str):
            raise AnthropicError("Claude asked for a tool without naming it")
        self._pending[index] = (tool_id, name)
        self._arguments[index] = []

    def _delta(self, event: JsonDict) -> str | None:
        index = event.get("index")
        delta = event.get("delta")
        if not isinstance(delta, dict):
            return None
        if delta.get("type") == "text_delta" and isinstance(delta.get("text"), str):
            text = str(delta["text"])
            self.text_parts.append(text)
            return text
        if (
            delta.get("type") == "input_json_delta"
            and isinstance(index, int)
            and isinstance(delta.get("partial_json"), str)
        ):
            self._arguments.setdefault(index, []).append(str(delta["partial_json"]))
        return None

    def _close_block(self, event: JsonDict) -> None:
        index = event.get("index")
        if not isinstance(index, int) or index not in self._pending:
            return
        tool_id, name = self._pending.pop(index)
        raw = "".join(self._arguments.pop(index, [])) or "{}"
        try:
            arguments = _ARGUMENTS.validate_python(json.loads(raw))
        except (ValueError, ValidationError) as exc:
            raise AnthropicError(f"Claude sent unusable arguments for {name}") from exc
        self.tools.append(ToolInvocation(id=tool_id, name=name, arguments=arguments))

    def _read_usage(self, holder: object) -> None:
        if not isinstance(holder, dict):
            return
        usage = holder.get("usage")
        if not isinstance(usage, dict):
            return
        reported_input = usage.get("input_tokens")
        reported_output = usage.get("output_tokens")
        if isinstance(reported_input, int):
            self.input_tokens = reported_input
        if isinstance(reported_output, int):
            self.output_tokens = reported_output

    def finish(self) -> TurnComplete:
        return TurnComplete(
            text="".join(self.text_parts),
            tools=tuple(self.tools),
            stop_reason=self.stop_reason,
        )


def _error_message(event: JsonDict) -> str:
    error = event.get("error")
    if isinstance(error, dict) and isinstance(error.get("type"), str):
        return str(error["type"])
    return "unknown"


class AnthropicToolClient:
    """A Messages API client that streams and can be given tools.

    Transport is injectable for the same reason as the single-shot client: tests assert on the
    exact stream the model would send without touching the network.
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = DEFAULT_BASE_URL,
        anthropic_version: str = DEFAULT_ANTHROPIC_VERSION,
        max_tokens: int,
        timeout: float,
        purpose: str = "chat",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.anthropic_version = anthropic_version
        self.max_tokens = max_tokens
        self.purpose = purpose
        self._client = MonitoredAsyncClient("anthropic", timeout=timeout, transport=transport)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def stream_turn(
        self,
        *,
        system: str,
        messages: Sequence[JsonDict],
        tools: Sequence[ToolDefinition] = (),
        on_usage: Callable[[str, int, int], None] | None = None,
    ) -> AsyncIterator[TurnEvent]:
        """One model call, streamed.

        `on_usage` receives (model, input tokens, output tokens) when the call ends, including
        when it fails: tokens already produced were billed, and a per-account cap that ignored a
        failed call would be a way to spend past it.
        """
        payload: JsonDict = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": 0,
            "system": system,
            "messages": list(messages),
            "stream": True,
        }
        if tools:
            payload["tools"] = [tool.as_payload() for tool in tools]

        accumulator = _Accumulator()
        try:
            async with self._client.stream(
                "POST",
                f"{self.base_url}/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": self.anthropic_version,
                    "content-type": "application/json",
                },
                json=payload,
            ) as response:
                if response.status_code >= 400:
                    # Read and discard: the body may name the account, and the status is what
                    # the caller can act on.
                    await response.aread()
                    raise AnthropicError(f"Claude returned HTTP {response.status_code}")
                async for line in response.aiter_lines():
                    event = _parse_line(line)
                    if event is None:
                        continue
                    text = accumulator.consume(event)
                    if text:
                        yield TextChunk(text=text)
        except httpx.HTTPError as exc:
            raise AnthropicError(f"Claude request failed: {exc}") from exc
        finally:
            # Metered even on a failed or abandoned stream: tokens already produced were billed.
            get_meter().record(
                model=self.model,
                input_tokens=accumulator.input_tokens,
                output_tokens=accumulator.output_tokens,
                purpose=self.purpose,
            )
            if on_usage is not None:
                on_usage(self.model, accumulator.input_tokens, accumulator.output_tokens)
        yield accumulator.finish()


def _parse_line(line: str) -> JsonDict | None:
    """One SSE `data:` line as JSON. Comments, `event:` lines and blanks carry nothing."""
    if not line.startswith("data:"):
        return None
    body = line[len("data:") :].strip()
    if not body:
        return None
    try:
        parsed = json.loads(body)
    except ValueError as exc:
        raise AnthropicError("Claude sent an unparseable stream event") from exc
    return parsed if isinstance(parsed, dict) else None
