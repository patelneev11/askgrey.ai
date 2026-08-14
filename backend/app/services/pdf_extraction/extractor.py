from __future__ import annotations

import json
from typing import Protocol

import httpx
from pydantic import BaseModel

from ..llm import (
    DEFAULT_ANTHROPIC_VERSION,
    DEFAULT_BASE_URL,
    AnthropicError,
    AnthropicMessagesClient,
    strip_code_fence,
)
from .errors import ExtractorError
from .models import ExtractionField, ParsedDocument

DEFAULT_CONTEXT_CHARS = 40_000

SYSTEM_PROMPT = """\
You extract structured data points from a research paper for a review table.

You are given the paper as numbered text blocks, each prefixed with its block id, and a list
of fields to fill in. Return ONLY a JSON object:

  {"data_points": [
     {"field": "<field key>",
      "value": "<the extracted value, concise>",
      "quote": "<verbatim substring of the block that states the value>",
      "block_id": "<id of the block the quote came from>"}
  ]}

Rules:
- `quote` MUST be copied character for character from a block. Never paraphrase, never merge
  text from two blocks, never repair typography. It should be the shortest span that still
  supports the value, normally one sentence or table row.
- Emit at most one object per field, and omit a field entirely if the paper does not state it.
  A missing field is correct; an invented one is not.
- Report values in the paper's own units and wording.
- Emit only the JSON object, with no code fence and no commentary.
"""


class RawDataPoint(BaseModel):
    """One candidate value from the model, before it is grounded against the parsed text."""

    field: str
    value: str
    quote: str = ""
    block_id: str = ""


class DataPointExtractor(Protocol):
    """Proposes values plus the quotes that support them. Grounding happens downstream."""

    name: str

    async def extract(
        self, document: ParsedDocument, fields: list[ExtractionField]
    ) -> list[RawDataPoint]: ...


def render_blocks(document: ParsedDocument, *, max_chars: int = DEFAULT_CONTEXT_CHARS) -> str:
    """
    Serialize blocks for the prompt, truncated to a character budget.

    The block that overruns the budget is cut mid-way rather than dropped, so a budget
    smaller than one block still yields usable context.
    """
    rendered: list[str] = []
    used = 0
    for block in document.blocks:
        chunk = f"[{block.block_id}] {block.text}"
        remaining = max_chars - used
        if remaining <= 0:
            break
        if len(chunk) > remaining:
            rendered.append(chunk[:remaining])
            break
        rendered.append(chunk)
        used += len(chunk)
    return "\n\n".join(rendered)


def render_fields(fields: list[ExtractionField]) -> str:
    return "\n".join(
        f"- {field.key}: {field.label}" + (f" — {field.description}" if field.description else "")
        for field in fields
    )


def parse_data_points(raw: str, fields: list[ExtractionField]) -> list[RawDataPoint]:
    """
    Read the model's JSON reply, keeping only well-formed points for known fields.

    The reply is a completion of a prefilled `{`, so the opening brace is re-attached before
    parsing. Points naming an unknown field are dropped rather than widening the table.
    """
    body = strip_code_fence(raw)
    if not body.startswith("{"):
        body = "{" + body
    try:
        data = json.loads(body)
    except ValueError as exc:
        raise ExtractorError("the model did not return valid JSON") from exc
    if not isinstance(data, dict):
        raise ExtractorError("the model did not return a JSON object")

    entries = data.get("data_points")
    if not isinstance(entries, list):
        raise ExtractorError("the model returned no data_points array")

    known = {field.key for field in fields}
    points: list[RawDataPoint] = []
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        key = str(entry.get("field", "")).strip()
        value = str(entry.get("value", "")).strip()
        if key not in known or key in seen or not value:
            continue
        seen.add(key)
        points.append(
            RawDataPoint(
                field=key,
                value=value,
                quote=str(entry.get("quote", "")),
                block_id=str(entry.get("block_id", "")).strip(),
            )
        )
    return points


class ClaudeDataPointExtractor:
    """Extraction through Anthropic's Messages API, mirroring the PubMed translator's setup."""

    name = "claude"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = DEFAULT_BASE_URL,
        anthropic_version: str = DEFAULT_ANTHROPIC_VERSION,
        max_tokens: int = 2048,
        timeout: float = 60.0,
        max_context_chars: int = DEFAULT_CONTEXT_CHARS,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.max_context_chars = max_context_chars
        self._client = AnthropicMessagesClient(
            api_key=api_key,
            model=model,
            base_url=base_url,
            anthropic_version=anthropic_version,
            max_tokens=max_tokens,
            timeout=timeout,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    def build_prompt(self, document: ParsedDocument, fields: list[ExtractionField]) -> str:
        return (
            "Fields to extract:\n"
            f"{render_fields(fields)}\n\n"
            "Paper:\n"
            f"{render_blocks(document, max_chars=self.max_context_chars)}"
        )

    async def extract(
        self, document: ParsedDocument, fields: list[ExtractionField]
    ) -> list[RawDataPoint]:
        try:
            text = await self._client.complete(
                system=SYSTEM_PROMPT,
                prompt=self.build_prompt(document, fields),
                prefill="{",
            )
        except AnthropicError as exc:
            raise ExtractorError(str(exc)) from exc
        return parse_data_points(text, fields)
