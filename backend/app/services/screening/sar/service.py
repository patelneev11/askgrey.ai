from __future__ import annotations

import logging

import httpx

from app.core.config import Settings, get_settings

from ...llm import AnthropicError
from ..smiles import parse_structure
from .descriptors import profile_structure
from .models import DescriptorProfile, SuggestionSet
from .suggestions import LlmSuggester, RuleBasedSuggester, SubstituentSuggester

logger = logging.getLogger(__name__)


class SarService:
    """
    The module's entry point: a SMILES string in, descriptors and suggestions out.

    Descriptors and suggestions are separate calls because they cost different things. The
    descriptor profile is a local calculation and cheap enough to run on every keystroke-driven
    submit; the suggestion set may spend money at Anthropic, so it sits behind its own
    (LLM-throttled) route and its own user action.
    """

    def __init__(self, *, suggester: SubstituentSuggester) -> None:
        self.suggester = suggester

    @classmethod
    def from_settings(
        cls,
        settings: Settings | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> SarService:
        settings = settings or get_settings()
        if settings.llm_translation_enabled:
            return cls(suggester=LlmSuggester.from_settings(settings, transport=transport))
        return cls(suggester=RuleBasedSuggester())

    async def aclose(self) -> None:
        await self.suggester.aclose()

    def profile(self, smiles: object) -> DescriptorProfile:
        """Deterministic descriptors and rule-set outcomes. Raises `InvalidStructureError`."""
        return profile_structure(smiles)

    async def suggestions(self, smiles: object) -> SuggestionSet:
        """
        Substituent suggestions for `smiles`, from Claude when configured.

        A Claude failure falls back to the deterministic heuristics rather than surfacing an
        error: the set names the suggester that produced it, so the answer stays truthful.
        """
        structure = parse_structure(smiles)
        profile = profile_structure(structure.input_smiles)
        try:
            return await self.suggester.suggest(structure.mol, profile)
        except AnthropicError as exc:
            logger.warning("sar.suggestions.llm_failed", extra={"reason": str(exc)})
            return await RuleBasedSuggester().suggest(structure.mol, profile)
