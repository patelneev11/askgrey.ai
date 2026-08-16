"""Protocol drafting, bench arithmetic, control validation and ELN export.

Drafted protocols are model output: they are structurally validated here and scientifically
validated nowhere, which is why `REVIEW_DISCLAIMER` travels on every draft. The calculator
package is the exception — it is deterministic arithmetic and may be labelled as calculated.
"""

from .checklist import ChecklistCategory, ChecklistItem, build_checklist
from .drafting import (
    SYSTEM_PROMPT,
    ClaudeProtocolDrafter,
    ProtocolDrafter,
    build_prompt,
    parse_draft,
)
from .errors import (
    DrafterError,
    DrafterUnavailableError,
    ProtocolError,
    ProtocolRequestError,
)
from .models import (
    REVIEW_DISCLAIMER,
    DraftOrigin,
    DraftRequest,
    ProtocolDraft,
    ProtocolMaterial,
    ProtocolStep,
)
from .service import ProtocolService
from .validation import (
    REVIEW_SCOPE_NOTE,
    ClaudeControlReviewer,
    ControlFinding,
    ControlKind,
    ControlReviewer,
    ControlStatus,
    ProtocolReview,
    ProtocolReviewRequest,
    parse_review,
    render_protocol,
)

__all__ = [
    "REVIEW_DISCLAIMER",
    "REVIEW_SCOPE_NOTE",
    "SYSTEM_PROMPT",
    "ChecklistCategory",
    "ChecklistItem",
    "ClaudeControlReviewer",
    "ClaudeProtocolDrafter",
    "ControlFinding",
    "ControlKind",
    "ControlReviewer",
    "ControlStatus",
    "DraftOrigin",
    "DraftRequest",
    "DrafterError",
    "DrafterUnavailableError",
    "ProtocolDraft",
    "ProtocolDrafter",
    "ProtocolError",
    "ProtocolMaterial",
    "ProtocolRequestError",
    "ProtocolReview",
    "ProtocolReviewRequest",
    "ProtocolService",
    "ProtocolStep",
    "build_checklist",
    "build_prompt",
    "parse_draft",
    "parse_review",
    "render_protocol",
]
