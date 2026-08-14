/**
 * Mirror of the backend extraction schema
 * (`backend/app/services/pdf_extraction/models.py`).
 *
 * The citation object is a stable contract: the backend only ever adds fields to it, so
 * these interfaces can be relied on by the viewer for highlight geometry.
 */

export type CellStatus = 'grounded' | 'ungrounded' | 'not_found';

/** How the quoted span was located in the parsed page — fuzzy spans must read differently. */
export type MatchQuality = 'exact' | 'normalized' | 'fuzzy';

export type RowStatus = 'extracted' | 'unsupported' | 'failed';

/** Page coordinates in points, origin top-left, `top` growing downwards. */
export interface BoundingBox {
  x0: number;
  top: number;
  x1: number;
  bottom: number;
}

export interface Citation {
  document_id: string;
  source_url: string;
  page_number: number;
  page_width: number;
  page_height: number;
  block_id: string;
  text: string;
  start_char: number;
  end_char: number;
  bbox: BoundingBox;
  rects: BoundingBox[];
  match: MatchQuality;
}

export interface ExtractionCell {
  value: string | null;
  citation: Citation | null;
  status: CellStatus;
  note: string;
}

export interface ExtractionField {
  key: string;
  label: string;
  description: string;
}

export interface PaperRow {
  document_id: string;
  title: string;
  source_url: string;
  filename: string;
  page_count: number;
  status: RowStatus;
  cells: Record<string, ExtractionCell>;
  warnings: string[];
}

export interface ExtractionTable {
  goal: string;
  columns: ExtractionField[];
  rows: PaperRow[];
}

export const EMPTY_TABLE: ExtractionTable = { goal: '', columns: [], rows: [] };

/** Identifies one cell across the table and the viewer. */
export function cellKey(documentId: string, columnKey: string): string {
  return `${documentId}::${columnKey}`;
}

export function rowLabel(row: PaperRow): string {
  return row.title || row.filename || row.document_id;
}

/**
 * Fold a fresh extraction run into the table already on screen.
 *
 * Each run covers one document and only the columns the user just asked for, so both axes
 * merge rather than replace: a re-run of the same goal over the same paper refreshes those
 * cells in place, and a new goal appends columns to every existing row. Column order is
 * generation order, which is what makes the table read as an audit of what was asked.
 */
export function mergeTables(base: ExtractionTable, incoming: ExtractionTable): ExtractionTable {
  const columns = [...base.columns];
  for (const column of incoming.columns) {
    const index = columns.findIndex((existing) => existing.key === column.key);
    if (index === -1) columns.push(column);
    else columns[index] = column;
  }

  const rows = [...base.rows];
  for (const row of incoming.rows) {
    const index = rows.findIndex((existing) => existing.document_id === row.document_id);
    if (index === -1) {
      rows.push(row);
    } else {
      rows[index] = { ...rows[index], ...row, cells: { ...rows[index].cells, ...row.cells } };
    }
  }

  const goals = [base.goal, incoming.goal].map((goal) => goal.trim()).filter(Boolean);
  return { goal: [...new Set(goals)].join('; '), columns, rows };
}

export function groundedCount(table: ExtractionTable): number {
  return table.rows.reduce(
    (total, row) =>
      total + Object.values(row.cells).filter((cell) => cell.status === 'grounded').length,
    0,
  );
}
