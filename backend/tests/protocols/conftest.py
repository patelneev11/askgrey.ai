from __future__ import annotations

import json
from typing import Any

import httpx

from app.services.protocols import ClaudeProtocolDrafter, DraftRequest

GOAL = "Design a Western blot protocol to measure p53 expression in MCF-7 cells post-treatment"


def draft_request(**kwargs: object) -> DraftRequest:
    payload: dict[str, object] = {"goal": GOAL}
    payload.update(kwargs)
    return DraftRequest.model_validate(payload)


def protocol_payload(**overrides: Any) -> dict[str, Any]:
    """A structurally complete reply, as the prompt asks for it. Science is not asserted."""
    payload: dict[str, Any] = {
        "title": "Western blot for p53 in treated MCF-7 cells",
        "assay_type": "western blot",
        "summary": "Lyse treated MCF-7 cells, resolve by SDS-PAGE and detect p53 by immunoblot.",
        "materials": [
            {
                "name": "RIPA lysis buffer with protease inhibitors",
                "amount": "200 uL per 6-well",
                "storage": "4 C",
                "note": "add inhibitors fresh",
            },
            {
                "name": "Anti-p53 primary antibody",
                "amount": "1:1000",
                "vendor_or_catalog": "clone DO-1",
                "storage": "-20 C",
            },
        ],
        "steps": [
            {
                "title": "Harvest treated cells",
                "instruction": "Wash wells twice with ice-cold PBS and scrape into 200 uL "
                "RIPA buffer.",
                "duration": "15 min",
                "temperature": "4 C",
                "equipment": ["cell scraper"],
                "critical_note": "keep lysates on ice to limit p53 degradation",
            },
            {
                "title": "Clear lysates",
                "instruction": "Centrifuge lysates at 14000 x g and keep the supernatant.",
                "duration": "10 min",
                "temperature": "4 C",
                "equipment": ["refrigerated microcentrifuge"],
            },
            {
                "title": "Immunoblot",
                "instruction": "Incubate the membrane with anti-p53 at 1:1000 overnight, "
                "including an untreated lysate as a negative control.",
                "duration": "overnight",
                "temperature": "4 C",
            },
        ],
        "total_duration": "2 days",
        "expected_outcomes": ["A 53 kDa band whose intensity rises with treatment"],
    }
    payload.update(overrides)
    return payload


def claude_response(payload: Any, *, status_code: int = 200) -> httpx.Response:
    """Wrap a body as the Messages API would, minus the prefilled opening brace."""
    text = payload if isinstance(payload, str) else json.dumps(payload)
    if text.startswith("{"):
        text = text[1:]
    return httpx.Response(
        status_code,
        json={
            "content": [{"type": "text", "text": text}],
            "usage": {"input_tokens": 800, "output_tokens": 900},
        },
    )


class RecordingTransport(httpx.AsyncBaseTransport):
    """Serves canned Claude replies and keeps the request bodies for prompt assertions."""

    def __init__(self, *responses: httpx.Response) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        index = min(len(self.requests) - 1, len(self.responses) - 1)
        return self.responses[index]

    @property
    def bodies(self) -> list[dict[str, Any]]:
        return [json.loads(request.content.decode()) for request in self.requests]


def make_drafter(*responses: httpx.Response) -> tuple[ClaudeProtocolDrafter, RecordingTransport]:
    transport = RecordingTransport(*responses)
    drafter = ClaudeProtocolDrafter(
        api_key="test-key",
        model="claude-test",
        transport=transport,
    )
    return drafter, transport
