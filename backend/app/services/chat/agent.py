"""
The chat turn: stream prose, run the tools the model asks for, and record what happened.

The loop is deliberately small. Everything the assistant can actually do lives in `tools.py` as
an adapter over a service the tabs already use, and everything it says about that work has to
come back through a tool result — which is why the trace is a first-class part of the response
rather than a debug view.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass

from pydantic import JsonValue

from app.core import audit
from app.services.chat.models import (
    ChatEvent,
    Citation,
    DoneEvent,
    ErrorEvent,
    NoticeEvent,
    TextEvent,
    ToolResultEvent,
    ToolStartEvent,
    ToolStep,
)
from app.services.chat.store import append_message
from app.services.chat.tools import ToolContext, ToolInputError, ToolRegistry
from app.services.llm.anthropic import AnthropicError
from app.services.llm.tool_use import (
    AnthropicToolClient,
    TextChunk,
    ToolInvocation,
    TurnComplete,
)

DEFAULT_MAX_STEPS = 6
# A tool result is fed back to the model, so its size is spend. Oversized results keep their first
# records rather than being replaced by a placeholder: a model handed "result too large" answers
# the question from memory and invents identifiers that look real, which is the one failure this
# whole design exists to prevent. The ceiling is generous enough that a single-compound ADMET
# profile and a ten-record search arrive whole, since those are the results most likely to be
# quoted back with identifiers.
MAX_DETAIL_CHARS = 24000

SYSTEM_PROMPT = """You are AskGrey's research assistant, working inside a biomedical R&D \
workspace alongside the researcher's Literature, Screening, Protocol, Regulatory and Grants tabs.

How to work:
- Use the tools for anything factual. They call the same services the tabs do, so their output is \
the researcher's real data, not an example.
- Never invent a PMID, NCT number, patent or application number, funding opportunity number, \
saved item id, or quotation. If a tool did not return it, you do not have it.
- When you have not run a tool, say what you would run instead of answering from memory.
- Refer to identifiers exactly as the tools returned them, so every claim can be checked.
- A result carrying `truncated` was cut before it reached you: you have `records_sent_to_you` of \
`records_the_tool_returned`, and the rest do not exist for you. State that count in your answer, \
never claim the full set was returned, and never fill the remainder in from memory. Any other \
count in the payload (a total matched by the query, say) is a different number and does not \
describe what you were given.
- Do not add a fact the tools did not return, not even one you are confident of, such as naming a \
compound the payload identifies only by formula. Say what the result says, and say the rest is not \
in it.

What the results are, and are not:
- ADMET and SAR output is model prediction with an applicability-domain caveat, never a \
measurement. Carry the caveat into your answer whenever you report one.
- Protocol, preclinical and IND text is an unvalidated draft that requires expert review.
- Eligibility and budget results come from explicit rules files. Report their verdicts as given; \
`needs_review` means the rules cannot decide, and you must not decide it for them.
- Patent search is keyword prior art, not a novelty or freedom-to-operate opinion.
- You do not give legal, regulatory or clinical advice.

What you cannot do:
- You cannot save, edit or delete the researcher's work, and you cannot file anything in an \
external electronic lab notebook. If they ask for that, name the tab that does it.

Be concise and specific. Prefer a short answer with identifiers over a long one without."""


@dataclass(frozen=True)
class ChatAgent:
    """One conversation turn, from the researcher's message to a persisted answer."""

    client: AnthropicToolClient
    registry: ToolRegistry
    max_steps: int = DEFAULT_MAX_STEPS

    async def run(
        self,
        *,
        context: ToolContext,
        conversation_id: str,
        history: Sequence[dict[str, object]],
        reference_context: str = "",
        client_ip: str | None = None,
    ) -> AsyncIterator[ChatEvent]:
        system = SYSTEM_PROMPT
        if reference_context:
            system = f"{SYSTEM_PROMPT}\n\n{reference_context}"
        messages: list[dict[str, object]] = list(history)
        answer: list[str] = []
        steps: list[ToolStep] = []
        stop_reason = ""

        try:
            for step_number in range(self.max_steps):
                turn: TurnComplete | None = None
                async for chunk in self.client.stream_turn(
                    system=system,
                    messages=messages,
                    tools=self.registry.definitions(),
                ):
                    if isinstance(chunk, TextChunk):
                        answer.append(chunk.text)
                        yield TextEvent(text=chunk.text)
                    else:
                        turn = chunk
                if turn is None:
                    raise AnthropicError("Claude closed the stream without finishing the turn")
                stop_reason = turn.stop_reason
                if not turn.tools:
                    break
                messages.append({"role": "assistant", "content": _assistant_blocks(turn)})
                results: list[dict[str, object]] = []
                for invocation in turn.tools:
                    async for event in self._run_tool(
                        invocation, context=context, conversation_id=conversation_id, ip=client_ip
                    ):
                        if isinstance(event, ToolResultEvent):
                            steps.append(event.step)
                            results.append(_tool_result_block(event.step))
                        yield event
                messages.append({"role": "user", "content": results})
                if step_number == self.max_steps - 1:
                    yield NoticeEvent(
                        message=(
                            f"Stopped after {self.max_steps} tool steps. Ask a narrower question "
                            "to continue."
                        )
                    )
        except AnthropicError as exc:
            audit.record(
                "chat.turn_failed",
                outcome="failure",
                actor=context.user_id,
                client_ip=client_ip,
                detail={"conversation_id": conversation_id, "reason": type(exc).__name__},
                db=context.db,
                user_id=context.user_id,
            )
            message = await self._persist(context, conversation_id, answer, steps)
            yield ErrorEvent(message=str(exc))
            yield DoneEvent(conversation_id=conversation_id, message_id=message)
            return
        finally:
            await self.client.aclose()

        if stop_reason == "max_tokens":
            yield NoticeEvent(
                message="The reply hit its length limit and stops mid-answer; ask for the rest."
            )
        message_id = await self._persist(context, conversation_id, answer, steps)
        audit.record(
            "chat.turn_completed",
            actor=context.user_id,
            client_ip=client_ip,
            detail={
                "conversation_id": conversation_id,
                "tool_steps": len(steps),
                "answer_chars": len("".join(answer)),
                "stop_reason": stop_reason,
            },
            db=context.db,
            user_id=context.user_id,
        )
        yield DoneEvent(conversation_id=conversation_id, message_id=message_id)

    async def _run_tool(
        self,
        invocation: ToolInvocation,
        *,
        context: ToolContext,
        conversation_id: str,
        ip: str | None,
    ) -> AsyncIterator[ChatEvent]:
        tool = self.registry.get(invocation.name)
        if tool is None:
            # Reachable: the model can hallucinate a tool name, and the turn should continue.
            step = ToolStep(
                id=invocation.id,
                tool=invocation.name,
                title=invocation.name,
                ok=False,
                summary="no such tool",
            )
            yield ToolResultEvent(step=step)
            return

        arguments = invocation.arguments
        yield ToolStartEvent(
            id=invocation.id, tool=tool.name, title=tool.title, arguments=arguments
        )
        detail: JsonValue = None
        citations: tuple[Citation, ...] = ()
        try:
            outcome = await tool.run(context, arguments)
        except ToolInputError as exc:
            outcome_ok, summary = False, str(exc)
        else:
            outcome_ok = outcome.ok
            summary = outcome.summary
            detail = _bounded(outcome.detail)
            citations = outcome.citations
        audit.record(
            "chat.tool_call",
            outcome="success" if outcome_ok else "failure",
            actor=context.user_id,
            client_ip=ip,
            detail={"conversation_id": conversation_id, "tool": tool.name},
            db=context.db,
            user_id=context.user_id,
        )
        yield ToolResultEvent(
            step=ToolStep(
                id=invocation.id,
                tool=tool.name,
                title=tool.title,
                arguments=arguments,
                ok=outcome_ok,
                summary=summary,
                citations=list(citations),
                detail=detail,
            )
        )

    async def _persist(
        self,
        context: ToolContext,
        conversation_id: str,
        answer: Sequence[str],
        steps: Sequence[ToolStep],
    ) -> str:
        text = "".join(answer)
        if not text and not steps:
            # Nothing was produced, so there is no turn worth reopening.
            return ""
        message = append_message(
            context.db,
            conversation_id=conversation_id,
            user_id=context.user_id,
            role="assistant",
            text=text,
            steps=tuple(steps),
        )
        return message.id


def _assistant_blocks(turn: TurnComplete) -> list[dict[str, object]]:
    """The turn as the API needs it echoed back, so the tool results attach to their requests."""
    blocks: list[dict[str, object]] = []
    if turn.text.strip():
        blocks.append({"type": "text", "text": turn.text})
    blocks.extend(
        {
            "type": "tool_use",
            "id": invocation.id,
            "name": invocation.name,
            "input": invocation.arguments,
        }
        for invocation in turn.tools
    )
    return blocks


def _tool_result_block(step: ToolStep) -> dict[str, object]:
    # `step.detail` is already bounded; the summary rides on top of it, so the envelope gets its own
    # allowance rather than slicing a record in half to hit the same number.
    payload = json.dumps({"summary": step.summary, "result": step.detail}, separators=(",", ":"))[
        : MAX_DETAIL_CHARS + 1000
    ]
    return {
        "type": "tool_result",
        "tool_use_id": step.id,
        "content": payload,
        "is_error": not step.ok,
    }


def _measure(detail: JsonValue) -> int:
    return len(json.dumps(detail, separators=(",", ":")))


def _fewer_records(records: list[JsonValue], budget: int) -> list[JsonValue]:
    """The longest prefix of `records` that serialises within `budget`."""
    kept: list[JsonValue] = []
    for record in records:
        if _measure([*kept, record]) > budget:
            break
        kept.append(record)
    return kept


def _cut_notice(*, sent: int, returned: int, field: str = "") -> dict[str, JsonValue]:
    """
    Say what was withheld in words the reader of the payload cannot mistake for something else.

    Terse keys were read as a display detail and the answer then claimed every record had arrived,
    so the counts name who received them and the note states the obligation outright.
    """
    notice: dict[str, JsonValue] = {
        "records_sent_to_you": sent,
        "records_the_tool_returned": returned,
        "note": (
            f"Only the first {sent} of {returned} records were sent to you; the remaining "
            f"{returned - sent} were not, and you do not have them. Report only the records above, "
            f"tell the researcher you are showing {sent} of {returned}, and offer a narrower "
            "search for the rest."
        ),
    }
    if field:
        notice["cut_field"] = field
    return notice


def _bounded(detail: JsonValue) -> JsonValue:
    """
    Keep a payload the browser can render a card from, and stop well short of a whole paper.

    An oversized result is shortened, never withheld. A search returns its records under one key,
    so the longest of those lists loses its tail and the payload says what it dropped; the model is
    told in the system prompt that a `truncated` result must not be completed from memory.
    """
    if detail is None:
        return None
    if _measure(detail) <= MAX_DETAIL_CHARS:
        return detail
    if isinstance(detail, list):
        kept = _fewer_records(detail, MAX_DETAIL_CHARS - 600)
        return {
            "records": kept,
            "truncated": _cut_notice(sent=len(kept), returned=len(detail)),
        }
    if isinstance(detail, dict):
        lists = {key: value for key, value in detail.items() if isinstance(value, list) and value}
        if lists:
            longest = max(lists, key=lambda key: _measure(lists[key]))
            records = lists[longest]
            # The rest of the payload is metadata the answer needs (query, model, caveats), so the
            # records get whatever is left of the budget after it.
            overhead = _measure({**detail, longest: []})
            kept = _fewer_records(records, max(MAX_DETAIL_CHARS - overhead - 600, 0))
            trimmed: dict[str, JsonValue] = {**detail, longest: kept}
            trimmed["truncated"] = _cut_notice(sent=len(kept), returned=len(records), field=longest)
            if _measure(trimmed) <= MAX_DETAIL_CHARS:
                return trimmed
    text = json.dumps(detail, separators=(",", ":"))[: MAX_DETAIL_CHARS - 600]
    return {
        "partial_json": text,
        "truncated": {
            "note": (
                "This result was cut mid-record before it reached you, so it is incomplete and the "
                "missing part was not sent to you. Say the result was too large to return in full "
                "and ask for a narrower query rather than answering from memory."
            )
        },
    }
