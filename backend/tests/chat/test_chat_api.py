"""The chat tab end to end: threads, a streamed turn, its tool trace, and its boundaries.

Claude is scripted rather than mocked away, so the turns here are the byte shapes the real API
sends: a tool request, then an answer that uses the result. What the tools do is real — they read
the same rows the tabs read, under the caller's own account.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api import chat as chat_api
from app.api import deps
from app.api.chat import get_chat_agent
from app.core.config import Settings, get_settings
from app.main import app
from app.services.chat.agent import ChatAgent
from app.services.chat.tools import ToolRegistry
from app.services.llm.tool_use import AnthropicToolClient
from tests.chat.test_tool_use import sse
from tests.test_library_api import descriptors, save

OWNER = {"email": "chatter@askgrey.ai", "password": "obsidian-workspace-1"}
OTHER = {"email": "onlooker@askgrey.ai", "password": "obsidian-workspace-2"}


def keyless_settings() -> Settings:
    """A deployment that never configured a Claude key, whatever this machine's environment is."""
    return get_settings().model_copy(update={"anthropic_api_key": ""})


def auth(client: TestClient, credentials: dict[str, str]) -> dict[str, str]:
    tokens = client.post("/api/auth/register", json=credentials).json()
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def tool_turn(name: str, arguments: dict[str, Any]) -> bytes:
    return sse(
        {"type": "message_start", "message": {"usage": {"input_tokens": 30}}},
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "tool_use", "id": "toolu_1", "name": name},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "input_json_delta", "partial_json": json.dumps(arguments)},
        },
        {"type": "content_block_stop", "index": 0},
        {"type": "message_delta", "delta": {"stop_reason": "tool_use"}},
    )


def text_turn(text: str, *, stop_reason: str = "end_turn") -> bytes:
    return sse(
        {"type": "message_start", "message": {"usage": {"input_tokens": 40}}},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text}},
        {"type": "content_block_stop", "index": 0},
        {"type": "message_delta", "delta": {"stop_reason": stop_reason}},
    )


@pytest.fixture
def script() -> Iterator[list[bytes]]:
    """The turns Claude will 'send', in order, and the requests it was sent."""
    turns: list[bytes] = []
    app.dependency_overrides[get_chat_agent] = lambda: _agent(turns)
    yield turns
    app.dependency_overrides.pop(get_chat_agent, None)


def _agent(turns: list[bytes]) -> ChatAgent:
    def handler(_request: httpx.Request) -> httpx.Response:
        body = turns.pop(0) if turns else text_turn("Nothing further.")
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    client = AnthropicToolClient(
        api_key="test-key",
        model="claude-sonnet-4-5",
        max_tokens=256,
        timeout=5.0,
        transport=httpx.MockTransport(handler),
    )
    return ChatAgent(client=client, registry=ToolRegistry(), max_steps=3)


def send(
    client: TestClient,
    headers: dict[str, str],
    conversation_id: str,
    message: str,
    references: list[dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    response = client.post(
        f"/api/chat/conversations/{conversation_id}/messages",
        json={"message": message, "references": references or []},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    return [
        json.loads(frame[len("data: ") :])
        for frame in response.text.split("\n\n")
        if frame.startswith("data: ")
    ]


def new_conversation(client: TestClient, headers: dict[str, str]) -> str:
    response = client.post("/api/chat/conversations", json={}, headers=headers)
    assert response.status_code == 201, response.text
    conversation_id: str = response.json()["id"]
    return conversation_id


def test_the_tab_can_list_what_the_assistant_is_able_to_do(client: TestClient) -> None:
    headers = auth(client, OWNER)

    tools = client.get("/api/chat/tools", headers=headers).json()

    names = {tool["name"] for tool in tools}
    assert {"search_pubmed", "predict_admet", "read_literature_workspace"} <= names
    admet = next(tool for tool in tools if tool["name"] == "predict_admet")
    assert "prediction" in admet["description"]
    assert admet["tab"] == "Screening"


def test_a_thread_is_named_after_its_first_question(
    client: TestClient, script: list[bytes]
) -> None:
    headers = auth(client, OWNER)
    conversation_id = new_conversation(client, headers)
    script.append(text_turn("Two."))

    send(client, headers, conversation_id, "How many trials cite ziprasidone?")

    listed = client.get("/api/chat/conversations", headers=headers).json()
    assert listed[0]["title"] == "How many trials cite ziprasidone?"
    assert listed[0]["message_count"] == 2


def test_a_turn_streams_prose_then_records_the_answer(
    client: TestClient, script: list[bytes]
) -> None:
    headers = auth(client, OWNER)
    conversation_id = new_conversation(client, headers)
    script.append(text_turn("Two trials."))

    events = send(client, headers, conversation_id, "How many?")

    assert [event["text"] for event in events if event["type"] == "text"] == ["Two trials."]
    assert events[-1]["type"] == "done"
    thread = client.get(f"/api/chat/conversations/{conversation_id}", headers=headers).json()
    assert [(message["role"], message["text"]) for message in thread["messages"]] == [
        ("user", "How many?"),
        ("assistant", "Two trials."),
    ]


def test_a_tool_call_runs_against_the_callers_own_saved_work(
    client: TestClient, script: list[bytes]
) -> None:
    headers = auth(client, OWNER)
    intruder = auth(client, OTHER)
    save(
        client,
        headers,
        kind="screening_descriptors",
        payload=descriptors(client, headers),
        title="Aspirin descriptors",
    )
    conversation_id = new_conversation(client, intruder)
    script.extend([tool_turn("list_saved_work", {}), text_turn("You have nothing saved.")])

    events = send(client, intruder, conversation_id, "What have I saved?")

    started = next(event for event in events if event["type"] == "tool_start")
    assert started["tool"] == "list_saved_work"
    result = next(event for event in events if event["type"] == "tool_result")
    # The other account's artifact is invisible, not merely unmentioned.
    assert result["step"]["summary"] == "0 saved item(s)"
    assert result["step"]["citations"] == []


def test_a_tool_step_carries_its_citations_into_the_stored_trace(
    client: TestClient, script: list[bytes]
) -> None:
    headers = auth(client, OWNER)
    saved = save(
        client,
        headers,
        kind="screening_descriptors",
        payload=descriptors(client, headers),
        title="Aspirin descriptors",
    )
    conversation_id = new_conversation(client, headers)
    script.extend([tool_turn("list_saved_work", {}), text_turn("One item: Aspirin descriptors.")])

    events = send(client, headers, conversation_id, "What have I saved?")

    result = next(event for event in events if event["type"] == "tool_result")
    assert result["step"]["citations"][0]["identifier"] == saved["id"]
    thread = client.get(f"/api/chat/conversations/{conversation_id}", headers=headers).json()
    answer = thread["messages"][-1]
    assert answer["steps"][0]["tool"] == "list_saved_work"
    assert answer["steps"][0]["citations"][0]["label"] == "Aspirin descriptors"


def test_arguments_the_tool_rejects_come_back_as_a_failed_step_not_a_broken_turn(
    client: TestClient, script: list[bytes]
) -> None:
    headers = auth(client, OWNER)
    conversation_id = new_conversation(client, headers)
    script.extend(
        [tool_turn("open_saved_work", {"artifact_id": ""}), text_turn("I need a valid id.")]
    )

    events = send(client, headers, conversation_id, "Open my last result")

    result = next(event for event in events if event["type"] == "tool_result")
    assert result["step"]["ok"] is False
    assert "artifact_id" in result["step"]["summary"]
    assert events[-1]["type"] == "done"


def test_an_invented_tool_name_fails_its_step_only(client: TestClient, script: list[bytes]) -> None:
    headers = auth(client, OWNER)
    conversation_id = new_conversation(client, headers)
    script.extend([tool_turn("file_in_benchling", {}), text_turn("I cannot do that.")])

    events = send(client, headers, conversation_id, "Push this to our ELN")

    result = next(event for event in events if event["type"] == "tool_result")
    assert result["step"]["ok"] is False
    assert result["step"]["summary"] == "no such tool"


def test_the_tool_loop_stops_at_its_step_ceiling(client: TestClient, script: list[bytes]) -> None:
    headers = auth(client, OWNER)
    conversation_id = new_conversation(client, headers)
    script.extend([tool_turn("list_saved_work", {}) for _ in range(3)])

    events = send(client, headers, conversation_id, "Keep looking")

    notices = [event for event in events if event["type"] == "notice"]
    assert "3 tool steps" in notices[0]["message"]
    assert len([event for event in events if event["type"] == "tool_result"]) == 3


def test_a_truncated_answer_says_so(client: TestClient, script: list[bytes]) -> None:
    headers = auth(client, OWNER)
    conversation_id = new_conversation(client, headers)
    script.append(text_turn("The first of many", stop_reason="max_tokens"))

    events = send(client, headers, conversation_id, "Summarise everything")

    assert any("length limit" in event.get("message", "") for event in events)


def test_a_provider_failure_is_delivered_inside_the_stream(
    client: TestClient, script: list[bytes]
) -> None:
    headers = auth(client, OWNER)
    conversation_id = new_conversation(client, headers)
    script.append(sse({"type": "error", "error": {"type": "overloaded_error"}}))

    events = send(client, headers, conversation_id, "Anything")

    error = next(event for event in events if event["type"] == "error")
    assert "overloaded_error" in error["message"]
    assert events[-1]["type"] == "done"


def test_a_reference_to_the_callers_own_workspace_is_accepted(
    client: TestClient, script: list[bytes]
) -> None:
    headers = auth(client, OWNER)
    conversation_id = new_conversation(client, headers)
    script.append(text_turn("Your workspace is empty."))

    events = send(
        client,
        headers,
        conversation_id,
        "What is in my workspace?",
        references=[{"kind": "literature_workspace", "id": ""}],
    )

    assert events[-1]["type"] == "done"


def test_a_reference_to_another_accounts_work_is_refused(
    client: TestClient, script: list[bytes]
) -> None:
    headers = auth(client, OWNER)
    intruder = auth(client, OTHER)
    saved = save(
        client,
        headers,
        kind="screening_descriptors",
        payload=descriptors(client, headers),
        title="Aspirin descriptors",
    )
    conversation_id = new_conversation(client, intruder)

    response = client.post(
        f"/api/chat/conversations/{conversation_id}/messages",
        json={
            "message": "Explain this",
            "references": [{"kind": "saved_work", "id": saved["id"]}],
        },
        headers=intruder,
    )

    assert response.status_code == 422
    assert "no saved item" in response.text


def test_a_thread_belonging_to_somebody_else_does_not_exist(
    client: TestClient, script: list[bytes]
) -> None:
    headers = auth(client, OWNER)
    intruder = auth(client, OTHER)
    conversation_id = new_conversation(client, headers)

    assert (
        client.get(f"/api/chat/conversations/{conversation_id}", headers=intruder).status_code
        == 404
    )
    assert (
        client.delete(f"/api/chat/conversations/{conversation_id}", headers=intruder).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/chat/conversations/{conversation_id}/messages",
            json={"message": "hello"},
            headers=intruder,
        ).status_code
        == 404
    )


def test_deleting_a_thread_takes_its_messages_with_it(
    client: TestClient, script: list[bytes]
) -> None:
    headers = auth(client, OWNER)
    conversation_id = new_conversation(client, headers)
    script.append(text_turn("Two."))
    send(client, headers, conversation_id, "How many?")

    assert (
        client.delete(f"/api/chat/conversations/{conversation_id}", headers=headers).status_code
        == 204
    )
    assert client.get("/api/chat/conversations", headers=headers).json() == []


def test_a_turn_and_its_tools_are_audited_without_the_question_or_the_result(
    client: TestClient, script: list[bytes]
) -> None:
    headers = auth(client, OWNER)
    conversation_id = new_conversation(client, headers)
    script.extend([tool_turn("list_saved_work", {}), text_turn("Nothing saved.")])

    send(client, headers, conversation_id, "Do I have anything on ziprasidone?")

    feed = client.get("/api/audit/events", headers=headers).json()
    events = {event["event"]: event for event in feed["events"]}
    assert {"chat.message_sent", "chat.tool_call", "chat.turn_completed"} <= set(events)
    assert events["chat.tool_call"]["kind"] == "agent"
    assert events["chat.tool_call"]["detail"]["tool"] == "list_saved_work"
    assert "ziprasidone" not in json.dumps(feed)


def test_the_daily_llm_budget_stops_a_turn_before_the_model_is_called(
    client: TestClient, script: list[bytes]
) -> None:
    headers = auth(client, OWNER)
    conversation_id = new_conversation(client, headers)
    deps.llm_budget.limit = 0
    try:
        response = client.post(
            f"/api/chat/conversations/{conversation_id}/messages",
            json={"message": "How many?"},
            headers=headers,
        )
    finally:
        deps.llm_budget.limit = deps._settings.llm_daily_call_budget

    assert response.status_code == 429
    assert script == []


def test_the_tab_is_unavailable_rather_than_silent_without_an_api_key(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers = auth(client, OWNER)
    conversation_id = new_conversation(client, headers)
    monkeypatch.setattr(chat_api, "get_settings", lambda: keyless_settings())

    response = client.post(
        f"/api/chat/conversations/{conversation_id}/messages",
        json={"message": "How many?"},
        headers=headers,
    )

    assert response.status_code == 503
    assert "ANTHROPIC_API_KEY" in response.text


def test_chat_requires_authentication(client: TestClient) -> None:
    assert client.get("/api/chat/conversations").status_code == 401
    assert client.post("/api/chat/conversations", json={}).status_code == 401
    assert (
        client.post("/api/chat/conversations/anything/messages", json={"message": "x"}).status_code
        == 401
    )
