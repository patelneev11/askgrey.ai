"""
Renderings of a record: one document to read, one document to re-parse.

The HTML is a single self-contained file with no script, no remote stylesheet and no image: it
opens in a browser, pastes into a notebook's rich-text editor and prints, and there is nothing in
it for an ELN's sanitizer to strip. Every value that reaches it is escaped, because the protocol
text is model output edited by a researcher — `<script>` in a step title is untrusted input, not
markup this renderer should honour.
"""

from __future__ import annotations

import json
from html import escape

from .record import Block, BlockKind, ElnRecord

HTML_MEDIA_TYPE = "text/html; charset=utf-8"
MARKDOWN_MEDIA_TYPE = "text/markdown; charset=utf-8"
JSON_MEDIA_TYPE = "application/json"

_STYLE = """
body { font-family: -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
       max-width: 46rem; margin: 2rem auto; padding: 0 1rem; color: #1a1d21; line-height: 1.5; }
h1 { font-size: 1.5rem; margin-bottom: 0.25rem; }
h2 { font-size: 1.05rem; margin-top: 1.75rem; text-transform: uppercase;
     letter-spacing: 0.04em; color: #46505a; }
.notice { border: 1px solid #b45309; background: #fffbeb; color: #7c2d12;
          padding: 0.75rem 1rem; border-radius: 0.375rem; margin: 1rem 0 1.5rem; }
table { border-collapse: collapse; width: 100%; margin: 0.5rem 0 1rem; }
th, td { text-align: left; vertical-align: top; padding: 0.35rem 0.5rem;
         border-bottom: 1px solid #e2e6ea; font-size: 0.95rem; }
th { width: 34%; color: #46505a; font-weight: 600; }
footer { margin-top: 2.5rem; color: #6b7480; font-size: 0.85rem; }
"""


def _blocks_html(blocks: list[Block]) -> list[str]:
    """Consecutive list blocks of one kind become one list; text blocks stay paragraphs."""
    out: list[str] = []
    open_tag = ""
    for block in blocks:
        wanted = {BlockKind.BULLET: "ul", BlockKind.NUMBER: "ol"}.get(block.kind, "")
        if wanted != open_tag:
            if open_tag:
                out.append(f"</{open_tag}>")
            if wanted:
                out.append(f"<{wanted}>")
            open_tag = wanted
        item = escape(block.text)
        out.append(f"<li>{item}</li>" if wanted else f"<p>{item}</p>")
    if open_tag:
        out.append(f"</{open_tag}>")
    return out


def to_html(record: ElnRecord) -> str:
    parts = [
        "<!doctype html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>{escape(record.title)}</title>",
        f"<style>{_STYLE}</style></head><body>",
        f"<h1>{escape(record.title)}</h1>",
        f'<p class="notice">{escape(record.notice)}</p>',
    ]
    if record.fields:
        parts.append("<table>")
        parts.extend(
            f"<tr><th>{escape(name)}</th><td>{escape(value)}</td></tr>"
            for name, value in record.fields.items()
        )
        parts.append("</table>")
    for section in record.sections:
        if section.heading:
            parts.append(f"<h2>{escape(section.heading)}</h2>")
        parts.extend(_blocks_html(section.blocks))
    stamp = record.exported_at.isoformat(timespec="seconds")
    parts.append(f"<footer>Exported from AskGrey at {escape(stamp)}.</footer>")
    parts.append("</body></html>")
    return "\n".join(parts)


def to_markdown(record: ElnRecord) -> str:
    lines = [f"# {record.title}", "", f"> {record.notice}", ""]
    for name, value in record.fields.items():
        lines.append(f"- **{name}:** {value}")
    if record.fields:
        lines.append("")
    for section in record.sections:
        if section.heading:
            lines.extend([f"## {section.heading}", ""])
        counter = 0
        for block in section.blocks:
            if block.kind is BlockKind.BULLET:
                lines.append(f"- {block.text}")
            elif block.kind is BlockKind.NUMBER:
                counter += 1
                lines.append(f"{counter}. {block.text}")
            else:
                counter = 0
                lines.extend([block.text, ""])
        lines.append("")
    lines.append(f"_Exported from AskGrey at {record.exported_at.isoformat(timespec='seconds')}._")
    return "\n".join(lines).rstrip() + "\n"


def to_json(record: ElnRecord) -> str:
    """The record itself, for a notebook or script that would rather parse than read."""
    return json.dumps(record.model_dump(mode="json"), indent=2, sort_keys=False) + "\n"
