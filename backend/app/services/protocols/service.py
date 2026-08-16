from __future__ import annotations

from app.core.config import Settings, get_settings

from .drafting import ClaudeProtocolDrafter, ProtocolDrafter
from .errors import DrafterUnavailableError
from .models import DraftRequest, ProtocolDraft


class ProtocolService:
    """
    Drafts protocols from a natural-language goal.

    The drafter is injected, and there is no fallback: without a configured model the service
    refuses rather than assembling a template that would look drafted but was not.
    """

    def __init__(self, drafter: ProtocolDrafter | None = None) -> None:
        self.drafter = drafter

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> ProtocolService:
        settings = settings or get_settings()
        drafter: ProtocolDrafter | None = None
        if settings.anthropic_api_key:
            drafter = ClaudeProtocolDrafter(
                api_key=settings.anthropic_api_key,
                model=settings.llm_model,
                base_url=settings.anthropic_base_url,
                anthropic_version=settings.anthropic_version,
                max_tokens=settings.protocol_draft_max_tokens,
                timeout=settings.protocol_draft_timeout_seconds,
            )
        return cls(drafter)

    async def aclose(self) -> None:
        drafter = self.drafter
        if isinstance(drafter, ClaudeProtocolDrafter):
            await drafter.aclose()

    @property
    def drafting_enabled(self) -> bool:
        return self.drafter is not None

    async def draft(self, request: DraftRequest) -> ProtocolDraft:
        if self.drafter is None:
            raise DrafterUnavailableError(
                "protocol drafting needs a configured model; no draft was produced"
            )
        return await self.drafter.draft(request)
