"""Protocol drafting, bench arithmetic, control validation and ELN export.

Drafted protocols are model output: they are structurally validated here and scientifically
validated nowhere, which is why `REVIEW_DISCLAIMER` travels on every draft. The calculator
package is the exception — it is deterministic arithmetic and may be labelled as calculated.
"""

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

__all__ = [
    "REVIEW_DISCLAIMER",
    "SYSTEM_PROMPT",
    "ClaudeProtocolDrafter",
    "DraftOrigin",
    "DraftRequest",
    "DrafterError",
    "DrafterUnavailableError",
    "ProtocolDraft",
    "ProtocolDrafter",
    "ProtocolError",
    "ProtocolMaterial",
    "ProtocolRequestError",
    "ProtocolService",
    "ProtocolStep",
    "build_prompt",
    "parse_draft",
]
