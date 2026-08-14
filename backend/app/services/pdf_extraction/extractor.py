from __future__ import annotations

import json
import re
from typing import Protocol

import httpx
from pydantic import BaseModel

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


def _strip_code_fence(content: str) -> str:
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z]*\n", "", stripped)
        stripped = re.sub(r"\n?```$", "", stripped)
    return stripped.strip()


def parse_data_points(raw: str, fields: list[ExtractionField]) -> list[RawDataPoint]:
    """
    Read the model's JSON reply, keeping only well-formed points for known fields.

    The reply is a completion of a prefilled `{`, so the opening brace is re-attached before
    parsing. Points naming an unknown field are dropped rather than widening the table.
    """
    body = _strip_code_fence(raw)
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
        base_url: str = "https://api.anthropic.com/v1",
        anthropic_version: str = "2023-06-01",
        max_tokens: int = 2048,
        timeout: float = 60.0,
        max_context_chars: int = DEFAULT_CONTEXT_CHARS,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.anthropic_version = anthropic_version
        self.max_tokens = max_tokens
        self.max_context_chars = max_context_chars
        self._client = httpx.AsyncClient(timeout=timeout, transport=transport)

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
            response = await self._client.post(
                f"{self.base_url}/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": self.anthropic_version,
                    "content-type": "application/json",
                },
                json={
                    "model": self.model,
                    "max_tokens": self.max_tokens,
                    "temperature": 0,
                    "system": SYSTEM_PROMPT,
                    "messages": [
                        {"role": "user", "content": self.build_prompt(document, fields)},
                        {"role": "assistant", "content": "{"},
                    ],
                },
            )
        except httpx.HTTPError as exc:
            raise ExtractorError(f"Claude request failed: {exc}") from exc

        if response.status_code >= 400:
            raise ExtractorError(f"Claude returned HTTP {response.status_code}")
        try:
            blocks = response.json()["content"]
        except (ValueError, KeyError, TypeError) as exc:
            raise ExtractorError("Claude response had an unexpected shape") from exc
        text = "".join(
            block["text"]
            for block in blocks
            if isinstance(block, dict) and isinstance(block.get("text"), str)
        )
        if not text.strip():
            raise ExtractorError("Claude returned no text content")
        return parse_data_points(text, fields)
