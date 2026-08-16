"""
Deterministic extraction of the critical-reagent checklist from a protocol's own text.

Storage temperatures, centrifuge speeds and handling warnings are pulled out with explicit
patterns rather than asked of a model: every item quotes the text it came from, so the checklist
cannot introduce a temperature or a speed the protocol never stated. Nothing here judges whether
the stated value is correct — that is the researcher's call.
"""

from __future__ import annotations

import re
from enum import Enum

from pydantic import BaseModel, Field

from .models import ProtocolDraft

MAX_ITEMS = 80


class ChecklistCategory(str, Enum):
    __str__ = str.__str__

    STORAGE = "storage"
    SPIN_SPEED = "spin_speed"
    HANDLING = "handling"
    TIMING = "timing"


class ChecklistItem(BaseModel):
    """One flagged detail, with the phrase it was extracted from."""

    id: str = Field(min_length=1, max_length=120)
    category: ChecklistCategory
    subject: str = Field(min_length=1, max_length=200)
    detail: str = Field(min_length=1, max_length=300)
    quote: str = Field(default="", max_length=400)
    step_id: str = Field(default="", max_length=100)
    step_order: int | None = None


# Temperatures written the way benches write them: "-20 C", "-80°C", "4 degrees C", "37C".
_TEMPERATURE = re.compile(r"(-?\d{1,3}(?:\.\d)?)\s*(?:°|º)?\s*(?:degrees?\s*)?C\b", re.IGNORECASE)
# Named conditions that carry a storage/handling requirement without a number.
_CONDITIONS = (
    ("on ice", "Keep on ice"),
    ("ice-cold", "Use ice-cold"),
    ("room temperature", "Room temperature"),
    ("liquid nitrogen", "Liquid nitrogen"),
    ("snap-freeze", "Snap-freeze"),
    ("snap freeze", "Snap-freeze"),
)
# Relative centrifugal force or rpm, with or without the "x g".
_SPEED = re.compile(
    r"(\d[\d,]*(?:\.\d+)?)\s*(?:×|x)?\s*(?:g\b|rcf\b|rpm\b)",
    re.IGNORECASE,
)
_HANDLING_TERMS = (
    ("light-sensitive", "Light-sensitive"),
    ("light sensitive", "Light-sensitive"),
    ("protect from light", "Light-sensitive"),
    ("do not vortex", "Do not vortex"),
    ("do not freeze", "Do not freeze"),
    ("freeze-thaw", "Freeze-thaw sensitive"),
    ("freeze/thaw", "Freeze-thaw sensitive"),
    ("aliquot", "Aliquot to avoid repeat thaws"),
    ("single use", "Single use"),
    ("single-use", "Single use"),
    ("prepare fresh", "Prepare fresh"),
    ("freshly prepared", "Prepare fresh"),
    ("add fresh", "Add fresh"),
    ("protease inhibitor", "Protease inhibitors"),
    ("phosphatase inhibitor", "Phosphatase inhibitors"),
    ("rnase-free", "RNase-free technique"),
    ("rnase free", "RNase-free technique"),
    ("dnase", "Nuclease handling"),
    ("sterile", "Sterile technique"),
    ("filter-sterilize", "Filter-sterilise"),
    ("biosafety", "Biosafety containment"),
    ("hazard", "Hazardous"),
    ("toxic", "Toxic"),
    ("carcinogen", "Carcinogen"),
    ("flammable", "Flammable"),
    ("acrylamide", "Acrylamide is a neurotoxin"),
    ("phenol", "Phenol is corrosive"),
    ("chloroform", "Chloroform is hazardous"),
)
_TIMING_TERMS = ("overnight", "immediately", "within", "do not exceed", "no longer than")


def _quote(text: str, match_start: int, match_end: int, *, width: int = 60) -> str:
    start = max(0, match_start - width)
    end = min(len(text), match_end + width)
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(text) else ""
    return prefix + text[start:end].strip() + suffix


def _temperature_items(
    text: str, *, subject: str, prefix: str, step_id: str, step_order: int | None
) -> list[ChecklistItem]:
    items: list[ChecklistItem] = []
    seen: set[str] = set()
    for match in _TEMPERATURE.finditer(text):
        value = f"{match.group(1)} C"
        if value in seen:
            continue
        seen.add(value)
        items.append(
            ChecklistItem(
                id=f"{prefix}-temp-{len(items) + 1}",
                category=ChecklistCategory.STORAGE,
                subject=subject,
                detail=value,
                quote=_quote(text, match.start(), match.end()),
                step_id=step_id,
                step_order=step_order,
            )
        )
    lowered = text.lower()
    for token, label in _CONDITIONS:
        if token in lowered and label not in seen:
            seen.add(label)
            index = lowered.index(token)
            items.append(
                ChecklistItem(
                    id=f"{prefix}-cond-{len(items) + 1}",
                    category=ChecklistCategory.STORAGE,
                    subject=subject,
                    detail=label,
                    quote=_quote(text, index, index + len(token)),
                    step_id=step_id,
                    step_order=step_order,
                )
            )
    return items


def _speed_items(
    text: str, *, subject: str, prefix: str, step_id: str, step_order: int | None
) -> list[ChecklistItem]:
    items: list[ChecklistItem] = []
    seen: set[str] = set()
    for match in _SPEED.finditer(text):
        detail = " ".join(match.group(0).split())
        if detail.lower() in seen:
            continue
        seen.add(detail.lower())
        items.append(
            ChecklistItem(
                id=f"{prefix}-spin-{len(items) + 1}",
                category=ChecklistCategory.SPIN_SPEED,
                subject=subject,
                detail=detail,
                quote=_quote(text, match.start(), match.end()),
                step_id=step_id,
                step_order=step_order,
            )
        )
    return items


def _term_items(
    text: str,
    terms: tuple[tuple[str, str], ...],
    *,
    category: ChecklistCategory,
    subject: str,
    prefix: str,
    step_id: str,
    step_order: int | None,
) -> list[ChecklistItem]:
    lowered = text.lower()
    items: list[ChecklistItem] = []
    seen: set[str] = set()
    for token, label in terms:
        if token not in lowered or label in seen:
            continue
        seen.add(label)
        index = lowered.index(token)
        items.append(
            ChecklistItem(
                id=f"{prefix}-{category}-{len(items) + 1}",
                category=category,
                subject=subject,
                detail=label,
                quote=_quote(text, index, index + len(token)),
                step_id=step_id,
                step_order=step_order,
            )
        )
    return items


def build_checklist(protocol: ProtocolDraft) -> list[ChecklistItem]:
    """
    Flag storage, spin-speed, handling and timing details stated in the protocol.

    Materials are scanned for storage and handling; steps for all four categories, since a spin
    speed or an overnight incubation only appears in the method.
    """
    items: list[ChecklistItem] = []

    for index, material in enumerate(protocol.materials, start=1):
        prefix = f"material-{index}"
        text = " ".join(part for part in (material.storage, material.note, material.amount) if part)
        if not text:
            continue
        items.extend(
            _temperature_items(
                text, subject=material.name, prefix=prefix, step_id="", step_order=None
            )
        )
        items.extend(
            _term_items(
                text,
                _HANDLING_TERMS,
                category=ChecklistCategory.HANDLING,
                subject=material.name,
                prefix=prefix,
                step_id="",
                step_order=None,
            )
        )

    for step in protocol.steps:
        prefix = step.id
        text = " ".join(
            part for part in (step.instruction, step.temperature, step.critical_note) if part
        )
        subject = f"Step {step.order}: {step.title}"[:200]
        items.extend(
            _temperature_items(
                text, subject=subject, prefix=prefix, step_id=step.id, step_order=step.order
            )
        )
        items.extend(
            _speed_items(
                text, subject=subject, prefix=prefix, step_id=step.id, step_order=step.order
            )
        )
        items.extend(
            _term_items(
                text,
                _HANDLING_TERMS,
                category=ChecklistCategory.HANDLING,
                subject=subject,
                prefix=prefix,
                step_id=step.id,
                step_order=step.order,
            )
        )
        timing_text = " ".join(part for part in (step.instruction, step.duration) if part)
        items.extend(
            _term_items(
                timing_text,
                tuple((token, token.capitalize()) for token in _TIMING_TERMS),
                category=ChecklistCategory.TIMING,
                subject=subject,
                prefix=prefix,
                step_id=step.id,
                step_order=step.order,
            )
        )

    return items[:MAX_ITEMS]
