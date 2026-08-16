from __future__ import annotations

from app.core.config import Settings, get_settings

from .checklist import ChecklistItem, build_checklist
from .drafting import ClaudeProtocolDrafter, ProtocolDrafter
from .errors import DrafterUnavailableError
from .models import DraftRequest, ProtocolDraft
from .validation import ClaudeControlReviewer, ControlReviewer, ProtocolReview


class ProtocolService:
    """
    Drafts protocols from a natural-language goal.

    The drafter is injected, and there is no fallback: without a configured model the service
    refuses rather than assembling a template that would look drafted but was not.
    """

    def __init__(
        self,
        drafter: ProtocolDrafter | None = None,
        reviewer: ControlReviewer | None = None,
    ) -> None:
        self.drafter = drafter
        self.reviewer = reviewer

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> ProtocolService:
        settings = settings or get_settings()
        drafter: ProtocolDrafter | None = None
        reviewer: ControlReviewer | None = None
        if settings.anthropic_api_key:
            drafter = ClaudeProtocolDrafter(
                api_key=settings.anthropic_api_key,
                model=settings.llm_model,
                base_url=settings.anthropic_base_url,
                anthropic_version=settings.anthropic_version,
                max_tokens=settings.protocol_draft_max_tokens,
                timeout=settings.protocol_draft_timeout_seconds,
            )
            reviewer = ClaudeControlReviewer(
                api_key=settings.anthropic_api_key,
                model=settings.llm_model,
                base_url=settings.anthropic_base_url,
                anthropic_version=settings.anthropic_version,
                max_tokens=settings.protocol_review_max_tokens,
                timeout=settings.protocol_draft_timeout_seconds,
            )
        return cls(drafter, reviewer)

    async def aclose(self) -> None:
        if isinstance(self.drafter, ClaudeProtocolDrafter):
            await self.drafter.aclose()
        if isinstance(self.reviewer, ClaudeControlReviewer):
            await self.reviewer.aclose()

    @property
    def drafting_enabled(self) -> bool:
        return self.drafter is not None

    async def draft(self, request: DraftRequest) -> ProtocolDraft:
        if self.drafter is None:
            raise DrafterUnavailableError(
                "protocol drafting needs a configured model; no draft was produced"
            )
        return await self.drafter.draft(request)

    async def review_controls(self, protocol: ProtocolDraft) -> ProtocolReview:
        if self.reviewer is None:
            raise DrafterUnavailableError(
                "control review needs a configured model; no review was produced"
            )
        return await self.reviewer.review(protocol)

    def reagent_checklist(self, protocol: ProtocolDraft) -> list[ChecklistItem]:
        """Deterministic extraction, so the checklist works with or without a model."""
        return build_checklist(protocol)
