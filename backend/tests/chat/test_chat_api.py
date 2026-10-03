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
from sqlalchemy.orm import Session

from app.api import chat as chat_api
from app.api import deps
from app.api.chat import build_gate, get_chat_agent
from app.core.config import Settings, get_settings
from app.core.terms import TERMS_VERSION
from app.main import app
from app.services.chat import spend
from app.services.chat.agent import ChatAgent
from app.services.chat.scope import ScopeGate
from app.services.chat.tools import ToolRegistry
from app.services.llm.tool_use import AnthropicToolClient
from tests.chat.test_scope import classifier as scope_classifier
from tests.chat.test_tool_use import sse
from tests.pdf_extraction.conftest import fixture_bytes
from tests.test_library_api import descriptors, save

OWNER = {"email": "chatter@askgrey.ai", "password": "obsidian-workspace-1"}
OTHER = {"email": "onlooker@askgrey.ai", "password": "obsidian-workspace-2"}


def keyless_settings() -> Settings:
    """A deployment that never configured a Claude key, whatever this machine's environment is."""
    return get_settings().model_copy(update={"anthropic_api_key": ""})


def auth(client: TestClient, credentials: dict[str, str]) -> dict[str, str]:
    tokens = client.post(
        "/api/auth/register", json={**credentials, "accepted_terms_version": TERMS_VERSION}
    ).json()
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


@pytest.fixture(autouse=True)
def pattern_only_gate() -> Iterator[None]:
    """The scope gate every turn here passes through, with no classifier behind it.

    Without this the gate reaches for a cheap model whenever the machine running the tests has a
    key in its environment, which makes these assertions depend on a live Anthropic call. The
    classifier's own behaviour is tested against a mock transport in test_scope.py.
    """
    app.dependency_overrides[build_gate] = lambda: ScopeGate(classifier=None)
    yield
    app.dependency_overrides.pop(build_gate, None)


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


def test_a_turn_the_provider_refuses_says_so_instead_of_rendering_nothing(
    client: TestClient, script: list[bytes]
) -> None:
    """The provider's own safety layer declines with zero text; silence is not an answer."""
    headers = auth(client, OWNER)
    conversation_id = new_conversation(client, headers)
    script.append(text_turn("", stop_reason="refusal"))

    events = send(client, headers, conversation_id, "What is the LD50 of ricin in mice?")

    text = "".join(event.get("text", "") for event in events if event["type"] == "text")
    assert "declined to answer" in text
    assert events[-1]["type"] == "done"
    assert events[-1]["message_id"]

    messages = client.get(f"/api/chat/conversations/{conversation_id}", headers=headers).json()
    assert messages["messages"][-1]["role"] == "assistant"
    assert "declined to answer" in messages["messages"][-1]["text"]

    feed = client.get("/api/audit/events", headers=headers).json()
    completed = next(event for event in feed["events"] if event["event"] == "chat.turn_completed")
    assert completed["outcome"] == "failure"
    assert completed["detail"]["model_produced_no_answer"] is True


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


def test_an_off_topic_question_is_answered_from_the_config_without_calling_claude(
    client: TestClient, script: list[bytes]
) -> None:
    headers = auth(client, OWNER)
    conversation_id = new_conversation(client, headers)

    events = send(client, headers, conversation_id, "Write me a poem about the lab")

    assert [event["type"] for event in events] == ["text", "done"]
    assert "biomedical R&D" in events[0]["text"]
    # Nothing was spent: the scripted turn is still queued, and no tool ran.
    assert script == []
    thread = client.get(f"/api/chat/conversations/{conversation_id}", headers=headers).json()
    # The refusal is the thread's answer, so reopening it does not look like a lost message.
    assert [message["role"] for message in thread["messages"]] == ["user", "assistant"]
    assert "biomedical R&D" in thread["messages"][1]["text"]
    feed = client.get("/api/audit/events", headers=headers).json()
    refusal = next(event for event in feed["events"] if event["event"] == "chat.out_of_scope")
    assert refusal["outcome"] == "denied"
    assert refusal["detail"]["rule"] == "creative_writing"
    # A refusal is the assistant declining to work, so the Agent runs filter has to show it
    # next to the turns it replaced rather than filing it under the researcher's own actions.
    assert refusal["kind"] == "agent"


def test_an_account_that_keeps_being_refused_stops_paying_for_the_classifier(
    client: TestClient, script: list[bytes], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cost ceiling on refusals: a refused turn never reaches the dollar cap, so the gate
    stops asking the cheap model about an account that has just been refused."""
    calls: list[httpx.Request] = []
    app.dependency_overrides[build_gate] = lambda: ScopeGate(
        classifier=scope_classifier("OFFTOPIC", calls=calls)
    )
    monkeypatch.setattr(
        "app.services.chat.scope_abuse.get_settings",
        lambda: get_settings().model_copy(
            update={"chat_scope_refusals_before_cooldown": 1, "chat_scope_cooldown_minutes": 60}
        ),
    )
    headers = auth(client, OWNER)
    conversation_id = new_conversation(client, headers)

    first = send(client, headers, conversation_id, "plan my wedding seating chart")
    second = send(client, headers, conversation_id, "plan my birthday party instead")

    assert "biomedical R&D" in first[0]["text"]
    assert "biomedical R&D" in second[0]["text"]
    # The second refusal cost nothing at Anthropic, and no turn ran either way.
    assert len(calls) == 1
    assert script == []
    feed = client.get("/api/audit/events", headers=headers).json()
    rules = [
        event["detail"]["rule"] for event in feed["events"] if event["event"] == "chat.out_of_scope"
    ]
    assert rules == ["classifier_withheld", "classifier"]


def test_an_exhausted_dollar_cap_refuses_the_turn_and_names_the_reset(
    client: TestClient, script: list[bytes], db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers = auth(client, OWNER)
    conversation_id = new_conversation(client, headers)
    user_id = client.get("/api/auth/me", headers=headers).json()["id"]
    monkeypatch.setattr(
        spend,
        "get_settings",
        lambda: get_settings().model_copy(update={"chat_daily_cost_cap_usd": 0.01}),
    )
    spend.record_usage(
        db, user_id=user_id, model="claude-sonnet-4-5", input_tokens=100_000, output_tokens=10_000
    )

    events = send(client, headers, conversation_id, "Any new PubMed papers on olanzapine?")

    assert [event["type"] for event in events] == ["text", "done"]
    assert "daily assistant budget" in events[0]["text"]
    assert "resets at 00:00 UTC" in events[0]["text"]
    assert script == []


def test_the_tab_can_show_the_scope_rule_and_what_is_left_to_spend(client: TestClient) -> None:
    headers = auth(client, OWNER)

    limits = client.get("/api/chat/limits", headers=headers).json()

    assert limits["scope_version"]
    assert "Biomedical R&D" in limits["scope_purpose"]
    assert limits["daily_spent_usd"] == 0.0
    assert limits["daily_cap_usd"] > 0
    assert limits["monthly_cap_usd"] > 0
    assert limits["exhausted_cap"] == ""
    assert limits["max_tool_steps"] > 0
    assert limits["max_message_chars"] > 0


def test_a_turn_writes_its_dollar_cost_to_the_account_ledger(
    client: TestClient, script: list[bytes], db: Session
) -> None:
    headers = auth(client, OWNER)
    conversation_id = new_conversation(client, headers)
    script.extend([tool_turn("list_saved_work", {}), text_turn("Nothing saved.")])

    send(client, headers, conversation_id, "What compounds have I saved?")

    limits = client.get("/api/chat/limits", headers=headers).json()
    # Two model calls at the scripted token counts: small, but not zero, and per account.
    assert limits["daily_spent_usd"] > 0
    assert limits["monthly_spent_usd"] == limits["daily_spent_usd"]
    other = auth(client, OTHER)
    assert client.get("/api/chat/limits", headers=other).json()["daily_spent_usd"] == 0.0


def test_chat_requires_authentication(client: TestClient) -> None:
    assert client.get("/api/chat/conversations").status_code == 401
    assert client.post("/api/chat/conversations", json={}).status_code == 401
    assert (
        client.post("/api/chat/conversations/anything/messages", json={"message": "x"}).status_code
        == 401
    )


def attach(client: TestClient, headers: dict[str, str], name: str = "trial.pdf") -> dict[str, Any]:
    response = client.post(
        "/api/chat/attachments",
        files={"file": (name, fixture_bytes("trial_ziprasidone"), "application/pdf")},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    attachment: dict[str, Any] = response.json()
    return attachment


def test_an_attached_pdf_comes_back_as_an_id_the_turn_can_reference(
    client: TestClient, script: list[bytes]
) -> None:
    headers = auth(client, OWNER)
    conversation_id = new_conversation(client, headers)
    script.append(text_turn("The trial reports QTc change."))

    attachment = attach(client, headers)
    assert attachment["pages"] > 0
    assert attachment["characters"] > 0

    events = send(
        client,
        headers,
        conversation_id,
        "What does the attached trial report?",
        references=[{"kind": "document", "id": attachment["document_id"]}],
    )

    assert events[-1]["type"] == "done"


def test_a_file_belonging_to_another_account_is_not_readable_by_reference(
    client: TestClient, script: list[bytes]
) -> None:
    headers = auth(client, OWNER)
    intruder = auth(client, OTHER)
    attachment = attach(client, headers)
    conversation_id = new_conversation(client, intruder)

    response = client.post(
        f"/api/chat/conversations/{conversation_id}/messages",
        json={
            "message": "Read this",
            "references": [{"kind": "document", "id": attachment["document_id"]}],
        },
        headers=intruder,
    )

    assert response.status_code == 422
    assert "no attached file" in response.text


def test_an_upload_that_is_not_a_pdf_is_refused_before_it_is_parsed(client: TestClient) -> None:
    headers = auth(client, OWNER)

    response = client.post(
        "/api/chat/attachments",
        files={"file": ("notes.pdf", b"not a pdf at all", "application/pdf")},
        headers=headers,
    )

    assert response.status_code == 415


def test_attaching_a_file_is_audited_without_saying_what_it_is_called(client: TestClient) -> None:
    headers = auth(client, OWNER)

    attach(client, headers, name="ziprasidone-qtc-trial.pdf")

    feed = client.get("/api/audit/events", headers=headers).json()
    event = next(item for item in feed["events"] if item["event"] == "chat.file_attached")
    assert event["detail"]["pages"] > 0
    assert "ziprasidone" not in json.dumps(feed)


def test_attachments_require_authentication(client: TestClient) -> None:
    response = client.post(
        "/api/chat/attachments", files={"file": ("x.pdf", b"%PDF-1.7", "application/pdf")}
    )
    assert response.status_code == 401
