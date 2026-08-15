from __future__ import annotations

from app.services.export import ExportFile, ExportFormat, ExportOptions, ExportService
from app.services.pdf_extraction import (
    CellStatus,
    ExtractionCell,
    ExtractionField,
    ExtractionTable,
    PaperRow,
)

from .models import GrantBudget, money

# The review table's per-paper metadata (source URL, pages) and its citation sheet describe a
# document, and a budget line is not one — both are turned off rather than filled with blanks.
# The record column stays, relabelled: it carries the SF-424 section each line belongs to.
BUDGET_EXPORT_OPTIONS = ExportOptions(
    include_citations=False,
    include_metadata=False,
    record_label="Section",
    filename_stem="grant-budget",
)

COLUMNS = [
    ExtractionField(key="line", label="Line"),
    ExtractionField(key="basis", label="Basis"),
    ExtractionField(key="amount", label="Amount"),
]


def _row(row_id: str, section: str, line: str, basis: str, amount: str) -> PaperRow:
    values = {"line": line, "basis": basis, "amount": amount}
    return PaperRow(
        document_id=row_id,
        title=section,
        cells={
            key: ExtractionCell(value=value, status=CellStatus.GROUNDED)
            for key, value in values.items()
        },
    )


def to_extraction_table(budget: GrantBudget) -> ExtractionTable:
    """
    Project a budget into the review-table schema the Wave 1 export module already renders.

    Reusing `ExportService` rather than writing a second writer keeps one implementation of the
    things that are easy to get wrong — formula-injection escaping, illegal control characters,
    Excel's cell limits, the CSV BOM. The cost of the reuse is that amounts land as formatted
    text rather than numeric cells, because `ExtractionCell.value` is a string; a spreadsheet
    that must recompute its own subtotals would need a numeric cell type added to the exporter,
    not a separate budget writer.
    """
    totals = {
        "G": ("Total Direct Costs (A-F)", budget.total_direct),
        "I": ("Total Direct and Indirect Costs (G+H)", budget.total_direct_and_indirect),
        "K": ("Total Costs and Fee (I+J)", budget.total),
    }
    rows: list[PaperRow] = []
    for code in "ABCDEFGHIJK":
        if code in totals:
            title, amount = totals[code]
            rows.append(_row(code, f"{code}. {title}", title, "", f"{amount:,}"))
            continue
        section = budget.section(code)
        if section is None:
            continue
        rows.extend(
            _row(
                f"{code}-{index}",
                f"{code}. {section.title}",
                line.label,
                line.basis,
                f"{money(line.amount):,}",
            )
            for index, line in enumerate(section.lines)
        )

    header = " · ".join(
        part
        for part in (budget.project_title, budget.organization, f"{budget.period_months} months")
        if part
    )
    return ExtractionTable(
        goal=f"{budget.program.value} budget — {header}", columns=COLUMNS, rows=rows
    )


def render(budget: GrantBudget, fmt: ExportFormat = ExportFormat.XLSX) -> ExportFile:
    """The whole export path: budget in, downloadable file out, via the shared exporter."""
    return ExportService().render(to_extraction_table(budget), fmt, BUDGET_EXPORT_OPTIONS)
