"""The tool registry itself: what the model is offered, and what it cannot reach.

These call the tools directly rather than through a turn, because the properties that matter are
about the adapters: their schemas have to be legal for the Messages API, and every account-scoped
one has to be scoped by the caller rather than by the argument.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.services.chat.tools import TOOLS, ToolContext, ToolInputError, ToolRegistry
from app.services.literature import WorkspaceWrite, save_workspace
from app.services.protocols import ProtocolDraft, ProtocolStep
from app.services.protocols.history import create_protocol
from app.services.users import create_user

OWNER = ("owner@askgrey.ai", "obsidian-workspace-1")
OTHER = ("other@askgrey.ai", "obsidian-workspace-2")


def accounts(db: Session) -> tuple[str, str]:
    owner = create_user(db, email=OWNER[0], password=OWNER[1])
    other = create_user(db, email=OTHER[0], password=OTHER[1])
    return str(owner.id), str(other.id)


def draft() -> ProtocolDraft:
    return ProtocolDraft(
        title="Ziprasidone hERG panel",
        goal="Measure hERG block",
        assay_type="electrophysiology",
        summary="",
        materials=[],
        steps=[ProtocolStep(id="s1", order=1, title="Prepare cells", instruction="Thaw.")],
        total_duration="1 day",
        expected_outcomes=[],
        origin="agent_drafted",
        disclaimer="Unvalidated draft.",
        model="test",
    )


def test_every_tool_declares_an_object_schema_the_messages_api_accepts() -> None:
    for tool in TOOLS:
        definition = tool.definition()
        assert definition.name == tool.name
        assert definition.description.strip()
        assert definition.input_schema["type"] == "object"
        assert "properties" in definition.input_schema


def test_the_registry_resolves_by_name_and_ignores_an_invented_one() -> None:
    registry = ToolRegistry()

    assert registry.get("predict_admet") is not None
    assert registry.get("file_in_benchling") is None
    assert len(registry.definitions()) == len(TOOLS)


@pytest.mark.asyncio
async def test_the_workspace_tool_reads_the_callers_own_workspace(db: Session) -> None:
    owner_id, other_id = accounts(db)
    save_workspace(
        db,
        owner_id,
        WorkspaceWrite.model_validate(
            {
                "goal": "hERG liability",
                "sources": [
                    {"id": "s1", "label": "Trial paper", "kind": "url", "url": "https://x.test/p"}
                ],
            }
        ),
    )
    registry = ToolRegistry()
    tool = registry.get("read_literature_workspace")
    assert tool is not None

    mine = await tool.run(ToolContext(db=db, user_id=owner_id), {})
    theirs = await tool.run(ToolContext(db=db, user_id=other_id), {})

    assert "1 paper(s)" in mine.summary
    assert "0 paper(s)" in theirs.summary
    assert theirs.citations == ()


@pytest.mark.asyncio
async def test_a_saved_protocol_cannot_be_opened_by_id_from_another_account(
    db: Session,
) -> None:
    owner_id, other_id = accounts(db)
    saved = create_protocol(db, user_id=owner_id, protocol=draft())
    registry = ToolRegistry()
    tool = registry.get("open_saved_protocol")
    assert tool is not None

    mine = await tool.run(ToolContext(db=db, user_id=owner_id), {"protocol_id": saved.id})
    theirs = await tool.run(ToolContext(db=db, user_id=other_id), {"protocol_id": saved.id})

    assert mine.ok is True
    assert "Ziprasidone hERG panel" in mine.summary
    assert theirs.ok is False
    assert "Ziprasidone" not in theirs.summary


@pytest.mark.asyncio
async def test_arguments_are_validated_against_the_tools_own_schema(db: Session) -> None:
    owner_id, _ = accounts(db)
    tool = ToolRegistry().get("predict_admet")
    assert tool is not None

    with pytest.raises(ToolInputError, match="smiles"):
        await tool.run(ToolContext(db=db, user_id=owner_id), {"structure": "aspirin"})


@pytest.mark.asyncio
async def test_admet_results_are_labelled_as_predictions(db: Session) -> None:
    owner_id, _ = accounts(db)
    tool = ToolRegistry().get("predict_admet")
    assert tool is not None

    outcome = await tool.run(
        ToolContext(db=db, user_id=owner_id), {"smiles": "CC(=O)OC1=CC=CC=C1C(=O)O"}
    )

    assert "predictions, not measurements" in outcome.summary
    assert outcome.ok is True


@pytest.mark.asyncio
async def test_no_tool_can_save_edit_or_delete_the_researchers_work() -> None:
    # Reading saved work is fine; writing it is what must not be reachable from a chat turn.
    for tool in TOOLS:
        assert not tool.name.startswith(("save", "delete", "update", "push", "send")), tool.name
        assert "eln" not in tool.name.split("_"), tool.name


def test_the_trial_search_offers_a_cursor_so_a_cut_result_can_be_continued() -> None:
    # Without a cursor the model answers a "find 50" request by retrying with ever larger pages,
    # which are cut again; the token is the only way past the records it was sent.
    tool = ToolRegistry().get("search_clinical_trials")
    assert tool is not None

    properties = tool.definition().input_schema["properties"]

    assert isinstance(properties, dict)
    assert "page_token" in properties
    assert "next_page_token" in tool.definition().description
