"""
The handoff bundle: one zip a researcher attaches to whatever notebook their lab actually runs.

This is the export that works today, for every ELN, without a vendor tenant or an API key. It
carries the same record three ways — a document to read, Markdown to paste, JSON to parse — plus
the instructions for the notebooks people actually use, so an import does not depend on the
researcher guessing which file their ELN accepts.

Nothing here performs a network call and no credential is read, so a bundle is safe to hand
straight to the browser as a download.
"""

from __future__ import annotations

import zipfile
from io import BytesIO

from app.services.export.models import ExportFile

from .record import ElnRecord
from .render import to_html, to_json, to_markdown

BUNDLE_MEDIA_TYPE = "application/zip"

DOCUMENT_NAME = "record.html"
MARKDOWN_NAME = "record.md"
JSON_NAME = "record.json"
README_NAME = "IMPORT.txt"

_README = """\
AskGrey ELN handoff bundle
==========================

{notice}

Files
-----
  {document}  The record as a printable document. Open it in a browser.
  {markdown}  The same content as Markdown, for pasting into a text editor.
  {json_name}  The same content as structured JSON, for a script or an import tool.

Getting this into your notebook
-------------------------------
Any ELN: attach the whole zip to an entry. The document stays readable without AskGrey.

LabArchives: create an entry, then either attach the zip, or open {document} in a
browser, select all, and paste into a Rich Text entry.

Benchling: create an entry and attach the zip, or paste {document} into a note. AskGrey can
also produce Benchling's documented entry JSON separately — that payload has never been run
against a live tenant, so it is labelled untested.

eLabFTW / SciNote / OneNote / Word: paste {document} into the editor. Formatting,
headings and step numbering survive the paste.

Provenance
----------
Exported from AskGrey at {stamp}.
Nothing in this bundle has been validated in a laboratory. Review it before bench use.
"""


def _readme(record: ElnRecord) -> str:
    return _README.format(
        notice=record.notice,
        document=DOCUMENT_NAME,
        markdown=MARKDOWN_NAME,
        json_name=JSON_NAME,
        stamp=record.exported_at.isoformat(timespec="seconds"),
    )


def build_bundle(record: ElnRecord) -> ExportFile:
    """Render the record into a zip. Byte-identical for the same record, so it can be diffed."""
    buffer = BytesIO()
    # Every member is stamped with the record's own export time rather than "now", which is what
    # makes two exports of one record compare equal instead of differing by a clock tick.
    stamp = (
        record.exported_at.year,
        record.exported_at.month,
        record.exported_at.day,
        record.exported_at.hour,
        record.exported_at.minute,
        record.exported_at.second,
    )
    members = (
        (README_NAME, _readme(record)),
        (DOCUMENT_NAME, to_html(record)),
        (MARKDOWN_NAME, to_markdown(record)),
        (JSON_NAME, to_json(record)),
    )
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, text in members:
            info = zipfile.ZipInfo(name, date_time=stamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, text.encode("utf-8"))
    return ExportFile(
        filename=f"{record.slug()}-eln.zip",
        media_type=BUNDLE_MEDIA_TYPE,
        content=buffer.getvalue(),
    )
