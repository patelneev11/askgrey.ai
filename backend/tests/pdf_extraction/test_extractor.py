from __future__ import annotations

import json

import httpx
import pytest

from app.services.pdf_extraction import (
    ClaudeDataPointExtractor,
    ExtractionField,
    ExtractorError,
    ParsedDocument,
    fields_from_goal,
)
from app.services.pdf_extraction.extractor import parse_data_points, render_blocks
from app.services.pdf_extraction.fetch import normalize_pmc_url

FIELDS = fields_from_goal("sample size, dosing regimen")


class StubTransport(httpx.AsyncBaseTransport):
    def __init__(self, response: httpx.Response | Exception) -> None:
        self.response = response
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def claude_reply(text: str) -> httpx.Response:
    return httpx.Response(200, json={"content": [{"type": "text", "text": text}]})


def extractor(
    response: httpx.Response | Exception,
) -> tuple[ClaudeDataPointExtractor, StubTransport]:
    transport = StubTransport(response)
    return (
        ClaudeDataPointExtractor(
            api_key="test-key", model="claude-sonnet-4-5", transport=transport
        ),
        transport,
    )


def test_completion_of_the_prefilled_brace_is_parsed() -> None:
    body = (
        '"data_points": [{"field": "sample_size", "value": "73",'
        ' "quote": "73 patients", "block_id": "p1-b4"}]}'
    )

    points = parse_data_points(body, FIELDS)

    assert len(points) == 1
    assert points[0].value == "73"
    assert points[0].block_id == "p1-b4"


def test_code_fenced_json_is_parsed() -> None:
    body = (
        '```json\n{"data_points": [{"field": "sample_size", "value": "73",'
        ' "quote": "73 patients"}]}\n```'
    )

    assert parse_data_points(body, FIELDS)[0].field == "sample_size"


def test_unknown_fields_and_duplicates_are_dropped() -> None:
    body = json.dumps(
        {
            "data_points": [
                {"field": "sample_size", "value": "73", "quote": "73 patients"},
                {"field": "sample_size", "value": "58", "quote": "58 patients"},
                {"field": "made_up", "value": "x", "quote": "y"},
                {"field": "dosing_regimen", "value": "", "quote": "empty value"},
                "not an object",
            ]
        }
    )

    points = parse_data_points(body, FIELDS)

    assert [(point.field, point.value) for point in points] == [("sample_size", "73")]


@pytest.mark.parametrize("body", ["not json at all", '"data_points": "nope"}', "[1, 2, 3]"])
def test_malformed_replies_raise(body: str) -> None:
    with pytest.raises(ExtractorError):
        parse_data_points(body, FIELDS)


def test_rendered_prompt_is_capped_and_labels_blocks(ziprasidone: ParsedDocument) -> None:
    rendered = render_blocks(ziprasidone, max_chars=500)

    assert rendered.startswith("[p1-b1]")
    assert len(rendered) <= 600


@pytest.mark.asyncio
async def test_extract_sends_blocks_and_fields(ziprasidone: ParsedDocument) -> None:
    client, transport = extractor(
        claude_reply(
            '"data_points": [{"field": "sample_size", "value": "73 patients",'
            ' "quote": "73 patients were randomized", "block_id": "p1-b4"}]}'
        )
    )

    points = await client.extract(ziprasidone, FIELDS)
    await client.aclose()

    assert [point.value for point in points] == ["73 patients"]
    payload = json.loads(transport.requests[0].content)
    assert payload["messages"][1] == {"role": "assistant", "content": "{"}
    assert "sample_size: sample size" in payload["messages"][0]["content"]
    assert "[p1-b4]" in payload["messages"][0]["content"]
    assert transport.requests[0].headers["x-api-key"] == "test-key"


@pytest.mark.asyncio
async def test_http_error_becomes_an_extractor_error(ziprasidone: ParsedDocument) -> None:
    client, _ = extractor(httpx.Response(529, text="overloaded"))

    with pytest.raises(ExtractorError, match="529"):
        await client.extract(ziprasidone, FIELDS)
    await client.aclose()


@pytest.mark.asyncio
async def test_transport_failure_becomes_an_extractor_error(ziprasidone: ParsedDocument) -> None:
    client, _ = extractor(httpx.ConnectError("connection reset"))

    with pytest.raises(ExtractorError, match="request failed"):
        await client.extract(ziprasidone, FIELDS)
    await client.aclose()


@pytest.mark.asyncio
async def test_empty_content_becomes_an_extractor_error(ziprasidone: ParsedDocument) -> None:
    client, _ = extractor(claude_reply("   "))

    with pytest.raises(ExtractorError, match="no text content"):
        await client.extract(ziprasidone, FIELDS)
    await client.aclose()


def test_api_key_is_required() -> None:
    with pytest.raises(ValueError):
        ClaudeDataPointExtractor(api_key="", model="claude-sonnet-4-5")


def test_field_labels_reach_the_prompt() -> None:
    field = ExtractionField(key="dose", label="dose", description="mg per day")

    assert field.description == "mg per day"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "https://pmc.ncbi.nlm.nih.gov/articles/PMC5334499/",
            "https://pmc.ncbi.nlm.nih.gov/articles/PMC5334499/pdf/",
        ),
        (
            "https://pmc.ncbi.nlm.nih.gov/articles/PMC5334499/pdf/",
            "https://pmc.ncbi.nlm.nih.gov/articles/PMC5334499/pdf/",
        ),
        (
            "https://journals.plos.org/plosone/article/file?id=10.1371/x&type=printable",
            "https://journals.plos.org/plosone/article/file?id=10.1371/x&type=printable",
        ),
    ],
)
def test_pmc_urls_resolve_to_the_pdf(url: str, expected: str) -> None:
    assert normalize_pmc_url(url) == expected
