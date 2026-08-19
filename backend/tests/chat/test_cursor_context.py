"""
Carrying a paging cursor from one turn to the next.

A tool result is not replayed into a later turn, so a cursor the previous answer received is gone
by the time the researcher types "show me more". Asked to continue without it, the model built a
token that looked like the API's and was rejected, so the real one is restated instead.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.services.chat.models import ToolStep
from app.services.chat.store import (
    ChatRequestError,
    append_message,
    create_conversation,
    cursor_context,
    known_page_tokens,
)
from app.services.users import create_user

TOKEN = "ZVt07cGHkvI2wRk2CJf6_LLqwpaccd8wd7KrgP4YlDeVtA"


def account(db: Session) -> str:
    return str(create_user(db, email="cursor@askgrey.ai", password="obsidian-workspace-1").id)


def answered(db: Session, user_id: str, step: ToolStep) -> str:
    conversation = create_conversation(db, user_id=user_id)
    append_message(
        db, conversation_id=conversation.id, user_id=user_id, role="user", text="find 50 trials"
    )
    append_message(
        db,
        conversation_id=conversation.id,
        user_id=user_id,
        role="assistant",
        text="Here are 50 trials.",
        steps=(step,),
    )
    return conversation.id


def trial_step(token: str) -> ToolStep:
    return ToolStep(
        id="toolu_1",
        tool="search_clinical_trials",
        title="Trial search",
        arguments={"intervention": "ziprasidone", "page_size": 50},
        summary="50 trial(s) returned of 159 matched",
        detail={"returned": 50, "next_page_token": token},
    )


def test_the_next_turn_is_handed_the_cursor_verbatim(db: Session) -> None:
    user_id = account(db)
    conversation_id = answered(db, user_id, trial_step(TOKEN))

    context = cursor_context(db, conversation_id=conversation_id, user_id=user_id)

    assert TOKEN in context, "the exact token has to survive: the model cannot re-derive it"
    assert "search_clinical_trials" in context
    assert "ziprasidone" in context, "the query it belongs to, so it is not used on another search"
    assert "copied exactly" in context


def test_a_turn_with_nothing_left_to_page_is_told_nothing(db: Session) -> None:
    user_id = account(db)
    conversation_id = answered(db, user_id, trial_step(""))

    assert cursor_context(db, conversation_id=conversation_id, user_id=user_id) == ""


def test_the_thread_remembers_which_cursors_were_really_issued(db: Session) -> None:
    user_id = account(db)
    conversation_id = answered(db, user_id, trial_step(TOKEN))

    tokens = known_page_tokens(db, conversation_id=conversation_id, user_id=user_id)

    assert tokens == frozenset({TOKEN})
    assert '{"pageNum":2}' not in tokens, "the guard's whole point: only what a tool handed back"


def test_a_thread_that_paged_nowhere_knows_no_cursors(db: Session) -> None:
    user_id = account(db)
    conversation_id = answered(db, user_id, trial_step(""))

    assert known_page_tokens(db, conversation_id=conversation_id, user_id=user_id) == frozenset()


def test_another_account_cannot_read_a_threads_cursors(db: Session) -> None:
    user_id = account(db)
    conversation_id = answered(db, user_id, trial_step(TOKEN))
    other_id = str(create_user(db, email="other@askgrey.ai", password="obsidian-workspace-2").id)

    with pytest.raises(ChatRequestError, match="no conversation with that id"):
        cursor_context(db, conversation_id=conversation_id, user_id=other_id)
