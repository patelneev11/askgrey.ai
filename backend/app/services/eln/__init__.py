"""
Notebook handoff: saved work rendered into files any electronic lab notebook can ingest.

Vendor APIs are the second step, not the first. Benchling issues tenants through sales and
LabArchives issues API keys per institution, so neither can be exercised from this repository
today; a bundle a researcher attaches to their own notebook can, and it is the same record a
vendor client would post once there is an account to test it against.
"""

from .bundle import (
    BUNDLE_MEDIA_TYPE,
    DOCUMENT_NAME,
    JSON_NAME,
    MARKDOWN_NAME,
    README_NAME,
    build_bundle,
)
from .record import (
    HANDOFF_NOTICE,
    Block,
    BlockKind,
    ElnRecord,
    Section,
    record_from_protocol,
)
from .render import to_html, to_json, to_markdown

__all__ = [
    "BUNDLE_MEDIA_TYPE",
    "DOCUMENT_NAME",
    "HANDOFF_NOTICE",
    "JSON_NAME",
    "MARKDOWN_NAME",
    "README_NAME",
    "Block",
    "BlockKind",
    "ElnRecord",
    "Section",
    "build_bundle",
    "record_from_protocol",
    "to_html",
    "to_json",
    "to_markdown",
]
