"""
Regulatory drafting aids.

Everything under this package produces *drafts* for a qualified regulatory affairs
professional. No output here is a determination of what a submission requires, and every
returned object carries that in its own data — see `REVIEW_NOTICE`.

Structural facts (CTD section numbers, jurisdiction expectations) may only come from the
documents catalogued in `docs/regulatory-sources.md`, never from a model's memory.
"""

REVIEW_NOTICE = (
    "Agent-drafted content. Requires qualified regulatory affairs review before any "
    "regulatory use."
)

__all__ = ["REVIEW_NOTICE"]
