"""
The tools the chat tab can run.

Every tool here is a thin adapter over a service the tabs already use: the chat is an
orchestration layer, not a second implementation of PubMed search, ADMET prediction or the
eligibility rules. Two properties are deliberate:

- No tool widens what the caller can see. Anything account-scoped is looked up with the caller's
  own user id, so a model cannot be talked into reading another account's work.
- Every tool is read-only, or returns a draft in its response. Saving, editing and deleting stay
  in the tabs where a human clicks the button, so a chat turn cannot mutate stored work.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TypeVar

from pydantic import BaseModel, Field, JsonValue, ValidationError
from sqlalchemy.orm import Session

from app.services.chat.models import Citation
from app.services.clinicaltrials import (
    MAX_PAGE_SIZE as MAX_TRIAL_PAGE_SIZE,
)
from app.services.clinicaltrials import (
    ClinicalTrialsRequestError,
    ClinicalTrialsResponseError,
    ClinicalTrialsService,
    TrialPhase,
    TrialRecord,
    TrialSearch,
    TrialStatus,
)
from app.services.clinicaltrials import (
    InvalidQueryError as TrialQueryError,
)
from app.services.grants import (
    GrantProgram,
    GrantSearch,
    GrantSource,
    GrantsRequestError,
    GrantsResponseError,
    GrantsService,
)
from app.services.grants import (
    InvalidQueryError as GrantQueryError,
)
from app.services.grants.budget import (
    BudgetCalculator,
    BudgetConfigError,
    BudgetInputError,
    BudgetRequest,
)
from app.services.grants.eligibility import (
    CompanyProfile,
    EligibilityChecker,
    EligibilityConfigError,
)
from app.services.library import ArtifactKind, LibraryRequestError, get_artifact, list_artifacts
from app.services.literature import get_workspace
from app.services.llm.tool_use import ToolDefinition
from app.services.protocols import (
    DrafterError,
    DrafterUnavailableError,
    DraftRequest,
    ProtocolRequestError,
    ProtocolService,
)
from app.services.protocols.history import get_protocol, list_protocols
from app.services.pubchem import (
    CompoundNotFoundError,
    InvalidIdentifierError,
    PubChemRequestError,
    PubChemResponseError,
    PubChemService,
)
from app.services.pubmed import (
    EntrezRequestError,
    EntrezResponseError,
    PubMedService,
    TranslationError,
)
from app.services.pubmed import (
    InvalidQueryError as PubMedQueryError,
)
from app.services.regulatory.guidelines import (
    GuidelineChecker,
    GuidelineConfigError,
    GuidelineInputError,
    Jurisdiction,
)
from app.services.screening import InvalidStructureError
from app.services.screening.admet import AdmetService
from app.services.screening.patents import (
    InvalidFilterError,
    InvalidKeywordError,
    PatentRequestError,
    PatentSearch,
    PatentsService,
)
from app.services.screening.sar import SarService

ModelT = TypeVar("ModelT", bound=BaseModel)


@dataclass(frozen=True)
class ToolContext:
    """Everything a tool is allowed to know: the caller's account, and a database session."""

    db: Session
    user_id: str


@dataclass(frozen=True)
class ToolOutcome:
    """What a tool produced: a line for the trace, the payload, and where it came from."""

    summary: str
    detail: JsonValue = None
    citations: tuple[Citation, ...] = ()
    ok: bool = True


Runner = Callable[[ToolContext, dict[str, JsonValue]], Awaitable[ToolOutcome]]


class ToolInputError(ValueError):
    """The model called a tool with arguments the tool's own schema rejects."""


@dataclass(frozen=True)
class ChatTool:
    """One callable tool: how the model sees it, and what running it does."""

    name: str
    title: str
    tab: str
    description: str
    input_schema: dict[str, JsonValue]
    run: Runner
    #: True when the tool itself calls Claude, so a turn's cost is legible in the trace.
    calls_model: bool = False

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            input_schema=dict(self.input_schema),
        )


def _rejection(exc: ValidationError) -> str:
    """Name the offending fields and why, and nothing else: a tool argument can carry draft text,
    and this string ends up in a trace card and in the log."""
    return "; ".join(
        f"{'.'.join(str(item) for item in error['loc']) or 'input'}: {error['msg']}"
        for error in exc.errors()[:5]
    )


def _tool(
    *,
    name: str,
    title: str,
    tab: str,
    description: str,
    input_model: type[ModelT],
    handler: Callable[[ToolContext, ModelT], Awaitable[ToolOutcome]],
    calls_model: bool = False,
) -> ChatTool:
    """Bind a typed handler to its schema, so arguments are validated before it runs."""

    async def run(context: ToolContext, arguments: dict[str, JsonValue]) -> ToolOutcome:
        try:
            parsed = input_model.model_validate(arguments)
        except ValidationError as exc:
            raise ToolInputError(_rejection(exc)) from exc
        return await handler(context, parsed)

    schema: dict[str, JsonValue] = dict(input_model.model_json_schema())
    return ChatTool(
        name=name,
        title=title,
        tab=tab,
        description=description,
        input_schema=schema,
        run=run,
        calls_model=calls_model,
    )


class NoArguments(BaseModel):
    """A tool whose only input is who is asking."""


async def _read_literature_workspace(context: ToolContext, _arguments: NoArguments) -> ToolOutcome:
    workspace = get_workspace(context.db, context.user_id)
    columns = [column.label for column in workspace.table.columns] if workspace.table else []
    extraction = f", {len(columns)} extracted column(s)" if columns else ", no extraction yet"
    return ToolOutcome(
        summary=f"{len(workspace.sources)} paper(s) in the Literature tab{extraction}",
        detail=workspace.model_dump(mode="json"),
        citations=tuple(
            Citation(
                label=source.label,
                source="literature workspace",
                identifier=source.document_id or source.id,
                url=source.url,
            )
            for source in workspace.sources[:10]
        ),
    )


class SavedWorkInput(BaseModel):
    kind: ArtifactKind | None = None


async def _list_saved_work(context: ToolContext, arguments: SavedWorkInput) -> ToolOutcome:
    artifacts = list_artifacts(context.db, user_id=context.user_id, kind=arguments.kind)
    return ToolOutcome(
        summary=f"{len(artifacts)} saved item(s)",
        detail=[artifact.model_dump(mode="json") for artifact in artifacts],
        citations=tuple(
            Citation(label=artifact.title, source=str(artifact.kind), identifier=artifact.id)
            for artifact in artifacts[:10]
        ),
    )


class ArtifactInput(BaseModel):
    artifact_id: str = Field(min_length=1, max_length=36)


async def _open_saved_work(context: ToolContext, arguments: ArtifactInput) -> ToolOutcome:
    try:
        artifact = get_artifact(
            context.db, artifact_id=arguments.artifact_id, user_id=context.user_id
        )
    except LibraryRequestError as exc:
        return ToolOutcome(summary=str(exc), ok=False)
    return ToolOutcome(
        summary=f"{artifact.title} ({artifact.kind})",
        detail=artifact.model_dump(mode="json"),
        citations=(
            Citation(label=artifact.title, source=str(artifact.kind), identifier=artifact.id),
        ),
    )


async def _list_saved_protocols(context: ToolContext, _arguments: NoArguments) -> ToolOutcome:
    protocols = list_protocols(context.db, user_id=context.user_id)
    return ToolOutcome(
        summary=f"{len(protocols)} saved protocol(s)",
        detail=[protocol.model_dump(mode="json") for protocol in protocols],
        citations=tuple(
            Citation(
                label=protocol.title,
                source="saved protocol",
                identifier=f"{protocol.id} v{protocol.current_version}",
            )
            for protocol in protocols[:10]
        ),
    )


class ProtocolInput(BaseModel):
    protocol_id: str = Field(min_length=1, max_length=36)


async def _open_saved_protocol(context: ToolContext, arguments: ProtocolInput) -> ToolOutcome:
    try:
        saved = get_protocol(context.db, protocol_id=arguments.protocol_id, user_id=context.user_id)
    except ProtocolRequestError as exc:
        return ToolOutcome(summary=str(exc), ok=False)
    return ToolOutcome(
        summary=f"{saved.protocol.title} (version {saved.version})",
        detail=saved.model_dump(mode="json"),
        citations=(
            Citation(
                label=saved.protocol.title,
                source="saved protocol",
                identifier=f"{saved.id} v{saved.version}",
            ),
        ),
    )


class PubMedInput(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    limit: int = Field(default=10, ge=1, le=25)


async def _search_pubmed(_context: ToolContext, arguments: PubMedInput) -> ToolOutcome:
    service = PubMedService.from_settings()
    try:
        result = await service.search(arguments.query, limit=arguments.limit)
    except PubMedQueryError as exc:
        return ToolOutcome(summary=str(exc), ok=False)
    except (TranslationError, EntrezRequestError, EntrezResponseError) as exc:
        return ToolOutcome(summary=f"PubMed search failed: {exc}", ok=False)
    finally:
        await service.aclose()
    return ToolOutcome(
        summary=(
            f"{result.total_results} hit(s), {len(result.articles)} returned "
            f"for `{result.query.term}`"
        ),
        detail=result.model_dump(mode="json"),
        citations=tuple(
            Citation(
                label=article.title or article.pmid,
                source="PubMed",
                identifier=article.pmid,
                url=article.pubmed_url,
            )
            for article in result.articles
        ),
    )


class CompoundInput(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    limit: int = Field(default=5, ge=1, le=25)


async def _lookup_compound(_context: ToolContext, arguments: CompoundInput) -> ToolOutcome:
    service = PubChemService.from_settings()
    try:
        lookup = await service.lookup(arguments.query, limit=arguments.limit)
    except (InvalidIdentifierError, CompoundNotFoundError) as exc:
        return ToolOutcome(summary=str(exc), ok=False)
    except (PubChemRequestError, PubChemResponseError) as exc:
        return ToolOutcome(summary=f"PubChem request failed: {exc}", ok=False)
    finally:
        await service.aclose()
    return ToolOutcome(
        summary=f"{len(lookup.candidates)} PubChem candidate(s), resolved as {lookup.resolved_as}",
        detail=lookup.model_dump(mode="json"),
        citations=tuple(
            Citation(
                label=candidate.compound.title or str(candidate.compound.cid),
                source="PubChem",
                identifier=str(candidate.compound.cid),
                url=candidate.compound.pubchem_url,
            )
            for candidate in lookup.candidates[:10]
        ),
    )


class TrialInput(BaseModel):
    condition: str = Field(default="", max_length=200)
    intervention: str = Field(default="", max_length=200)
    sponsor: str = Field(default="", max_length=200)
    term: str = Field(default="", max_length=200)
    phases: list[TrialPhase] = Field(default_factory=list, max_length=8)
    statuses: list[TrialStatus] = Field(default_factory=list, max_length=12)
    page_size: int = Field(default=10, ge=1, le=MAX_TRIAL_PAGE_SIZE)
    page_token: str = Field(default="", max_length=400)


def _compact_trial(trial: TrialRecord) -> dict[str, JsonValue]:
    """The fields an answer about a trial cites, without the long titles and collaborator lists."""
    return {
        "nct_id": trial.nct_id,
        "title": trial.title[:160],
        "status": trial.status.value if trial.status else "",
        "phase": trial.phase_label,
        "sponsor": trial.sponsor[:80],
        "conditions": [condition[:60] for condition in trial.conditions[:3]],
        "interventions": [item.name[:60] for item in trial.interventions[:3]],
        "enrollment": trial.enrollment,
        "start_date": trial.start_date,
        "completion_date": trial.completion_date,
    }


async def _search_clinical_trials(_context: ToolContext, arguments: TrialInput) -> ToolOutcome:
    service = ClinicalTrialsService.from_settings()
    query = TrialSearch(
        sponsor=arguments.sponsor,
        condition=arguments.condition,
        intervention=arguments.intervention,
        term=arguments.term,
        phases=arguments.phases,
        statuses=arguments.statuses,
    )
    try:
        page = await service.search(
            query, page_size=arguments.page_size, page_token=arguments.page_token or None
        )
    except TrialQueryError as exc:
        return ToolOutcome(summary=str(exc), ok=False)
    except (ClinicalTrialsRequestError, ClinicalTrialsResponseError) as exc:
        return ToolOutcome(summary=f"ClinicalTrials.gov request failed: {exc}", ok=False)
    finally:
        await service.aclose()
    more = " — more pages available" if page.has_more else ""
    tally: Counter[str] = Counter(
        trial.status.value if trial.status else "UNSPECIFIED" for trial in page.trials
    )
    status_counts: dict[str, JsonValue] = dict(tally)
    return ToolOutcome(
        summary=f"{len(page.trials)} trial(s) returned of {page.total_count} matched{more}",
        # A page of full records overflows the turn's budget and gets cut, so the records are
        # projected to the fields an answer cites and the per-status tally is counted here: an
        # answer that has to count a long list itself gets the count wrong.
        detail={
            "query": query.model_dump(mode="json"),
            "returned": len(page.trials),
            "total_matched": page.total_count,
            "status_counts": status_counts,
            "next_page_token": page.next_page_token or "",
            "trials": [_compact_trial(trial) for trial in page.trials],
        },
        citations=tuple(
            Citation(
                label=trial.title or trial.nct_id,
                source="ClinicalTrials.gov",
                identifier=trial.nct_id,
                url=trial.url,
            )
            for trial in page.trials[:10]
        ),
    )


class StructureInput(BaseModel):
    smiles: str = Field(min_length=1, max_length=600)


async def _compute_descriptors(_context: ToolContext, arguments: StructureInput) -> ToolOutcome:
    service = SarService.from_settings()
    try:
        profile = service.profile(arguments.smiles)
    except InvalidStructureError as exc:
        return ToolOutcome(summary=str(exc), ok=False)
    finally:
        await service.aclose()
    return ToolOutcome(
        summary=f"RDKit descriptors for {profile.canonical_smiles}",
        detail=profile.model_dump(mode="json"),
    )


async def _predict_admet(_context: ToolContext, arguments: StructureInput) -> ToolOutcome:
    service = AdmetService()
    try:
        profile = service.evaluate(arguments.smiles)
    except InvalidStructureError as exc:
        return ToolOutcome(summary=str(exc), ok=False)
    return ToolOutcome(
        summary=(
            f"{len(profile.estimates)} ADMET endpoint(s) for {profile.canonical_smiles} — "
            "predictions, not measurements"
        ),
        detail=profile.model_dump(mode="json"),
    )


async def _search_patents(_context: ToolContext, arguments: PatentSearch) -> ToolOutcome:
    service = PatentsService.from_settings()
    try:
        landscape = await service.search(arguments)
    except (InvalidStructureError, InvalidKeywordError, InvalidFilterError) as exc:
        return ToolOutcome(summary=str(exc), ok=False)
    except PatentRequestError as exc:
        return ToolOutcome(summary=f"the patent search API rejected the query: {exc}", ok=False)
    finally:
        await service.aclose()
    return ToolOutcome(
        summary=(
            f"{landscape.returned} application(s) of {landscape.total_found} found — "
            "keyword prior art, not a novelty or freedom-to-operate assessment"
        ),
        detail=landscape.model_dump(mode="json"),
        citations=tuple(
            Citation(
                label=hit.title or hit.application_number,
                source="USPTO",
                identifier=hit.application_number,
                url=hit.url,
            )
            for hit in landscape.hits[:10]
        ),
    )


class GrantSearchInput(BaseModel):
    keyword: str = Field(default="", max_length=200)
    agency: str = Field(default="", max_length=200)
    program: GrantProgram | None = None
    open_only: bool = True
    page_size: int = Field(default=10, ge=1, le=25)


async def _search_grants(_context: ToolContext, arguments: GrantSearchInput) -> ToolOutcome:
    service = GrantsService.from_settings()
    query = GrantSearch(
        keyword=arguments.keyword,
        agency=arguments.agency,
        program=arguments.program,
        open_only=arguments.open_only,
        sources=[GrantSource.GRANTS_GOV, GrantSource.SBIR],
    )
    try:
        page = await service.search(query, page_size=arguments.page_size)
    except GrantQueryError as exc:
        return ToolOutcome(summary=str(exc), ok=False)
    except (GrantsRequestError, GrantsResponseError) as exc:
        return ToolOutcome(summary=f"grants search failed: {exc}", ok=False)
    finally:
        await service.aclose()
    return ToolOutcome(
        summary=f"{len(page.opportunities)} opportunity(ies) returned",
        detail=page.model_dump(mode="json"),
        citations=tuple(
            Citation(
                label=opportunity.title,
                source=str(opportunity.source),
                identifier=opportunity.number or opportunity.opportunity_id,
                url=opportunity.url,
            )
            for opportunity in page.opportunities[:10]
        ),
    )


class EligibilityInput(BaseModel):
    profile: CompanyProfile
    program: GrantProgram = GrantProgram.SBIR


async def _check_grant_eligibility(
    _context: ToolContext, arguments: EligibilityInput
) -> ToolOutcome:
    try:
        checker = EligibilityChecker.from_config_file()
        report = checker.check(arguments.profile, arguments.program)
    except EligibilityConfigError as exc:
        return ToolOutcome(summary=f"eligibility rules are unusable: {exc}", ok=False)
    except GrantQueryError as exc:
        return ToolOutcome(summary=str(exc), ok=False)
    return ToolOutcome(
        summary=(
            f"{report.verdict} under {report.program} rules, "
            f"{len(report.outcomes)} rule(s) evaluated (rules {report.config_version})"
        ),
        detail=report.model_dump(mode="json"),
    )


async def _build_grant_budget(_context: ToolContext, arguments: BudgetRequest) -> ToolOutcome:
    try:
        calculator = BudgetCalculator.from_config_file()
        budget = calculator.build(arguments)
    except BudgetConfigError as exc:
        return ToolOutcome(summary=f"budget rules are unusable: {exc}", ok=False)
    except BudgetInputError as exc:
        return ToolOutcome(summary=str(exc), ok=False)
    return ToolOutcome(
        summary=(
            f"{len(budget.sections)} SF-424 section(s), {len(budget.adjustments)} rule "
            f"adjustment(s) under rules {budget.rules_version}"
        ),
        detail=budget.model_dump(mode="json"),
    )


class GuidelineInput(BaseModel):
    section_id: str = Field(min_length=1, max_length=40)
    draft_text: str = Field(min_length=1, max_length=20000)
    jurisdictions: list[Jurisdiction] = Field(min_length=1, max_length=len(Jurisdiction))


async def _check_regulatory_guidelines(
    _context: ToolContext, arguments: GuidelineInput
) -> ToolOutcome:
    try:
        checker = GuidelineChecker.from_reference_files()
        report = checker.check(arguments.section_id, arguments.draft_text, arguments.jurisdictions)
    except GuidelineConfigError as exc:
        return ToolOutcome(summary=f"guideline reference data is unavailable: {exc}", ok=False)
    except GuidelineInputError as exc:
        return ToolOutcome(summary=str(exc), ok=False)
    findings = sum(len(jurisdiction.findings) for jurisdiction in report.jurisdictions)
    return ToolOutcome(
        summary=(
            f"{findings} finding(s) against section {report.section_id} across "
            f"{len(report.jurisdictions)} jurisdiction(s); requires expert review"
        ),
        detail=report.model_dump(mode="json"),
        citations=tuple(
            Citation(
                label=finding.title,
                source=str(jurisdiction.jurisdiction),
                identifier=finding.citation.document,
                url=finding.citation.url,
            )
            for jurisdiction in report.jurisdictions
            for finding in jurisdiction.findings[:5]
        ),
    )


async def _draft_protocol(_context: ToolContext, arguments: DraftRequest) -> ToolOutcome:
    service = ProtocolService.from_settings()
    try:
        draft = await service.draft(arguments)
    except DrafterUnavailableError as exc:
        return ToolOutcome(summary=str(exc), ok=False)
    except DrafterError as exc:
        return ToolOutcome(summary=f"drafting failed: {exc}", ok=False)
    finally:
        await service.aclose()
    return ToolOutcome(
        summary=(
            f"drafted `{draft.title}` with {len(draft.steps)} step(s) — agent-drafted and "
            "unvalidated, and not saved until you save it in the Protocol tab"
        ),
        detail=draft.model_dump(mode="json"),
    )


TOOLS: tuple[ChatTool, ...] = (
    _tool(
        name="read_literature_workspace",
        title="Literature workspace",
        tab="Literature",
        description=(
            "Read the caller's saved Literature workspace: the research goal, the papers queued "
            "in it, and the extracted review table with its per-cell citations. Use this before "
            "answering anything about 'my papers' or 'the table'."
        ),
        input_model=NoArguments,
        handler=_read_literature_workspace,
    ),
    _tool(
        name="list_saved_work",
        title="Saved work",
        tab="Workspace",
        description=(
            "List what the caller saved from the Screening, Regulatory and Grants tabs, newest "
            "first, optionally filtered to one kind. Returns titles and ids, not payloads."
        ),
        input_model=SavedWorkInput,
        handler=_list_saved_work,
    ),
    _tool(
        name="open_saved_work",
        title="Open saved item",
        tab="Workspace",
        description=(
            "Read one saved item in full by its id, including the caveats it was saved with."
        ),
        input_model=ArtifactInput,
        handler=_open_saved_work,
    ),
    _tool(
        name="list_saved_protocols",
        title="Saved protocols",
        tab="Protocol",
        description="List the caller's saved protocols with their current version numbers.",
        input_model=NoArguments,
        handler=_list_saved_protocols,
    ),
    _tool(
        name="open_saved_protocol",
        title="Open saved protocol",
        tab="Protocol",
        description="Read one saved protocol's current version in full, by its id.",
        input_model=ProtocolInput,
        handler=_open_saved_protocol,
    ),
    _tool(
        name="search_pubmed",
        title="PubMed search",
        tab="Literature",
        description=(
            "Search PubMed from a natural-language question. Returns the translated Entrez query "
            "and the matching records with their PMIDs and links."
        ),
        input_model=PubMedInput,
        handler=_search_pubmed,
        calls_model=True,
    ),
    _tool(
        name="lookup_compound",
        title="PubChem lookup",
        tab="Screening",
        description=(
            "Resolve a compound name, synonym or SMILES against PubChem. Returns ranked "
            "candidates with their CIDs and canonical structures."
        ),
        input_model=CompoundInput,
        handler=_lookup_compound,
    ),
    _tool(
        name="search_clinical_trials",
        title="Trial search",
        tab="Literature",
        description=(
            "Search ClinicalTrials.gov by condition, intervention, sponsor or free text, "
            "optionally filtered by phase and recruitment status. Paginated: to read past the "
            "records you were sent, call again with `page_token` set to the result's "
            "`next_page_token` rather than repeating the search with a larger `page_size`."
        ),
        input_model=TrialInput,
        handler=_search_clinical_trials,
    ),
    _tool(
        name="compute_descriptors",
        title="Descriptors",
        tab="Screening",
        description=(
            "Compute deterministic RDKit physicochemical descriptors and drug-likeness rule "
            "outcomes for one SMILES structure."
        ),
        input_model=StructureInput,
        handler=_compute_descriptors,
    ),
    _tool(
        name="predict_admet",
        title="ADMET prediction",
        tab="Screening",
        description=(
            "Estimate ADMET endpoints for one SMILES structure. Each endpoint carries its model "
            "basis, its benchmark metrics where it is a trained QSAR model, and its "
            "applicability-domain caveat. These are predictions, never measurements: report them "
            "with their caveats and never as assay results."
        ),
        input_model=StructureInput,
        handler=_predict_admet,
    ),
    _tool(
        name="search_patents",
        title="Patent search",
        tab="Screening",
        description=(
            "Keyword prior-art search over USPTO patent applications, from keywords and/or a "
            "structure. Not a structural search, and not a novelty or freedom-to-operate opinion."
        ),
        input_model=PatentSearch,
        handler=_search_patents,
    ),
    _tool(
        name="search_grants",
        title="Grant search",
        tab="Grants",
        description=(
            "Search open funding opportunities on grants.gov and SBIR.gov by keyword, agency and "
            "SBIR/STTR set-aside."
        ),
        input_model=GrantSearchInput,
        handler=_search_grants,
    ),
    _tool(
        name="check_grant_eligibility",
        title="Eligibility check",
        tab="Grants",
        description=(
            "Screen a structured company profile against the SBIR/STTR eligibility rules. "
            "Deterministic: every verdict comes from a numeric threshold in the rules file, and "
            "anything the rules cannot decide comes back as needs_review rather than a guess. "
            "Never override a verdict with your own judgement."
        ),
        input_model=EligibilityInput,
        handler=_check_grant_eligibility,
    ),
    _tool(
        name="build_grant_budget",
        title="Grant budget",
        tab="Grants",
        description=(
            "Cost line-item R&D estimates into an SF-424 (R&R) budget under the configured "
            "federal salary cap, indirect and fee rules."
        ),
        input_model=BudgetRequest,
        handler=_build_grant_budget,
    ),
    _tool(
        name="check_regulatory_guidelines",
        title="Guideline check",
        tab="Regulatory",
        description=(
            "Check one draft CTD section against the ICH/FDA/EMA guideline expectations for that "
            "section id in the requested jurisdictions. Returns findings with the guideline each "
            "one comes from."
        ),
        input_model=GuidelineInput,
        handler=_check_regulatory_guidelines,
    ),
    _tool(
        name="draft_protocol",
        title="Protocol draft",
        tab="Protocol",
        description=(
            "Draft a structured experimental protocol from a goal. The result is model output: "
            "unvalidated, and saved nowhere until the researcher saves it in the Protocol tab."
        ),
        input_model=DraftRequest,
        handler=_draft_protocol,
        calls_model=True,
    ),
)


@dataclass(frozen=True)
class ToolRegistry:
    """The tool set one chat turn may draw on. Injectable so tests can narrow it."""

    tools: tuple[ChatTool, ...] = TOOLS
    _by_name: dict[str, ChatTool] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        self._by_name.update({tool.name: tool for tool in self.tools})

    def get(self, name: str) -> ChatTool | None:
        return self._by_name.get(name)

    def definitions(self) -> list[ToolDefinition]:
        return [tool.definition() for tool in self.tools]
