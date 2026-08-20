"""
What the assistant will answer, decided before a turn is paid for.

An open chat box over a metered model is an open invoice: a question about the weather costs the
same tokens as a question about a trial, and a "keep going" prompt costs many of them. The policy
lives in `scope_rules.json` rather than only in the system prompt for the same reason the grant
thresholds do — it has to be editable, inspectable and cheap to apply, and a prompt-level rule
still spends a turn to say no.

Two stages, cheapest first:

1. Regular expressions from the config, run in-process. A blatantly out-of-scope message is
   refused without any Anthropic call at all, which is the only refusal that actually saves money.
2. A one-word classification by the cheap model, for everything the patterns do not settle and
   which carries none of the config's research vocabulary. Costs a few hundred input tokens
   against a full turn's thousands plus tool results.

Anything the classifier cannot decide, or fails to answer, is allowed through. A researcher
wrongly refused stops trusting the tab, whereas a wrongly allowed question costs one turn and is
still bounded by the spend caps in `spend.py`.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from app.core.config import get_settings
from app.services.llm.anthropic import AnthropicError, AnthropicMessagesClient

logger = logging.getLogger("askgrey.chat.scope")

DEFAULT_POLICY_PATH = Path(__file__).with_name("scope_rules.json")
# The classifier reads the message, not the thread: a long history would cost more than the turn
# it is protecting.
CLASSIFIER_INPUT_CHARS = 1000
CLASSIFIER_MAX_TOKENS = 8


class ScopePolicyError(RuntimeError):
    """The scope policy file is missing or malformed. Fails loudly: the gate is a control."""


class Decision(str, Enum):
    __str__ = str.__str__

    ALLOW = "allow"
    REFUSE = "refuse"


class OffTopicRule(BaseModel):
    id: str
    explanation: str
    patterns: list[str] = Field(default_factory=list)


class ClassifierSpec(BaseModel):
    system: str = ""
    in_scope_word: str = "RESEARCH"
    off_topic_word: str = "OFFTOPIC"


class ScopePolicy(BaseModel):
    """The editable policy, versioned so a refusal can name the rules that produced it."""

    version: str = ""
    purpose: str = ""
    refusal: str = ""
    comment: str = ""
    off_topic_rules: list[OffTopicRule] = Field(default_factory=list)
    in_scope_terms: list[str] = Field(default_factory=list)
    classifier: ClassifierSpec = Field(default_factory=ClassifierSpec)


@dataclass(frozen=True)
class ScopeVerdict:
    """One decision about one message, with the reason the tab shows the researcher."""

    decision: Decision
    rule: str = ""
    message: str = ""
    checked_by: str = "patterns"

    @property
    def allowed(self) -> bool:
        return self.decision is Decision.ALLOW


def load_policy(path: Path | None = None) -> ScopePolicy:
    source = path or DEFAULT_POLICY_PATH
    try:
        payload = json.loads(source.read_text())
    except FileNotFoundError as exc:
        raise ScopePolicyError(f"no chat scope policy at {source}") from exc
    except json.JSONDecodeError as exc:
        raise ScopePolicyError(f"chat scope policy at {source} is not valid JSON") from exc
    try:
        policy = ScopePolicy.model_validate(payload)
    except ValidationError as exc:
        raise ScopePolicyError(f"chat scope policy at {source} is malformed: {exc}") from exc
    for rule in policy.off_topic_rules:
        for pattern in rule.patterns:
            try:
                re.compile(pattern, re.IGNORECASE)
            except re.error as exc:
                raise ScopePolicyError(
                    f"rule '{rule.id}' has an unusable pattern {pattern!r}: {exc}"
                ) from exc
    return policy


@lru_cache
def get_policy() -> ScopePolicy:
    return load_policy()


@lru_cache(maxsize=1)
def _compiled(policy_version: str) -> tuple[tuple[str, str, re.Pattern[str]], ...]:
    """(rule id, explanation, pattern) for every rule, compiled once per policy version."""
    return tuple(
        (rule.id, rule.explanation, re.compile(pattern, re.IGNORECASE))
        for rule in get_policy().off_topic_rules
        for pattern in rule.patterns
    )


def _refusal(policy: ScopePolicy, rule_id: str, explanation: str, checked_by: str) -> ScopeVerdict:
    return ScopeVerdict(
        decision=Decision.REFUSE,
        rule=rule_id,
        message=(
            f"That reads as {explanation}, so I did not run it. {policy.refusal}"
            if explanation
            else policy.refusal
        ),
        checked_by=checked_by,
    )


def check_patterns(message: str, policy: ScopePolicy | None = None) -> ScopeVerdict:
    """The free half of the gate: refuse on a config pattern, without calling Claude."""
    active = policy or get_policy()
    for rule_id, explanation, pattern in _compiled(active.version):
        if pattern.search(message):
            return _refusal(active, rule_id, explanation, "patterns")
    return ScopeVerdict(decision=Decision.ALLOW, checked_by="patterns")


def mentions_research_vocabulary(message: str, policy: ScopePolicy | None = None) -> bool:
    """Whether the message carries a term from the config's research vocabulary."""
    active = policy or get_policy()
    lowered = message.lower()
    return any(term in lowered for term in active.in_scope_terms)


class ScopeGate:
    """The gate as the endpoint uses it: patterns, then the cheap model when they are silent."""

    def __init__(
        self,
        *,
        policy: ScopePolicy | None = None,
        classifier: AnthropicMessagesClient | None = None,
    ) -> None:
        self.policy = policy or get_policy()
        self.classifier = classifier

    async def check(self, message: str) -> ScopeVerdict:
        verdict = check_patterns(message, self.policy)
        if not verdict.allowed:
            return verdict
        if self.classifier is None or mentions_research_vocabulary(message, self.policy):
            return verdict
        return await self._classify(message, self.classifier)

    async def _classify(self, message: str, classifier: AnthropicMessagesClient) -> ScopeVerdict:
        spec = self.policy.classifier
        try:
            answer = await classifier.complete(
                system=spec.system,
                prompt=message[:CLASSIFIER_INPUT_CHARS],
                allow_truncated=True,
            )
        except AnthropicError as exc:
            # Allowed on purpose: a classifier outage must not close the tab, and the spend caps
            # still bound what an allowed turn can cost.
            logger.warning("chat scope classifier unavailable", extra={"reason": str(exc)})
            return ScopeVerdict(decision=Decision.ALLOW, checked_by="classifier_unavailable")
        finally:
            await classifier.aclose()
        word = answer.strip().upper()
        if word.startswith(spec.off_topic_word.upper()):
            return _refusal(
                self.policy,
                "classifier",
                "a question outside biomedical research work",
                "classifier",
            )
        return ScopeVerdict(decision=Decision.ALLOW, checked_by="classifier")


def build_gate() -> ScopeGate:
    """The gate for a request: pattern-only unless a cheap classifier is configured and keyed."""
    settings = get_settings()
    policy = get_policy()
    if not settings.chat_scope_gate_enabled:
        # The classifier is what a deployment can turn off; the patterns are free and stay on.
        return ScopeGate(policy=policy, classifier=None)
    if not settings.anthropic_api_key or not settings.chat_scope_model:
        return ScopeGate(policy=policy, classifier=None)
    classifier = AnthropicMessagesClient(
        api_key=settings.anthropic_api_key,
        model=settings.chat_scope_model,
        base_url=settings.anthropic_base_url,
        anthropic_version=settings.anthropic_version,
        max_tokens=CLASSIFIER_MAX_TOKENS,
        timeout=settings.chat_scope_timeout_seconds,
        purpose="chat_scope",
    )
    return ScopeGate(policy=policy, classifier=classifier)
