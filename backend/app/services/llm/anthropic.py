from __future__ import annotations

import re

import httpx

DEFAULT_BASE_URL = "https://api.anthropic.com/v1"
DEFAULT_ANTHROPIC_VERSION = "2023-06-01"


class AnthropicError(RuntimeError):
    """A Claude call that did not produce usable text. Callers re-raise in their own vocabulary."""


def strip_code_fence(content: str) -> str:
    """Drop a ```-fenced wrapper the model added despite being told not to."""
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z]*\n", "", stripped)
        stripped = re.sub(r"\n?```$", "", stripped)
    return stripped.strip()


class AnthropicMessagesClient:
    """
    One Messages API call, shared by every Claude-backed service.

    Each caller supplies its own system prompt and assistant prefill: the Messages API has no
    JSON response mode, so prefilling the opening `{` or `[` is what suppresses a prose
    preamble. Transport is injectable so tests never touch the network.
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
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.anthropic_version = anthropic_version
        self.max_tokens = max_tokens
        self._client = httpx.AsyncClient(timeout=timeout, transport=transport)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def complete(self, *, system: str, prompt: str, prefill: str = "") -> str:
        messages: list[dict[str, str]] = [{"role": "user", "content": prompt}]
        if prefill:
            messages.append({"role": "assistant", "content": prefill})

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
                    "system": system,
                    "messages": messages,
                },
            )
        except httpx.HTTPError as exc:
            raise AnthropicError(f"Claude request failed: {exc}") from exc

        if response.status_code >= 400:
            raise AnthropicError(f"Claude returned HTTP {response.status_code}")
        try:
            blocks = response.json()["content"]
        except (ValueError, KeyError, TypeError) as exc:
            raise AnthropicError("Claude response had an unexpected shape") from exc
        text = "".join(
            block["text"]
            for block in blocks
            if isinstance(block, dict) and isinstance(block.get("text"), str)
        )
        if not text.strip():
            raise AnthropicError("Claude returned no text content")
        return text
