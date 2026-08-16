import {
  cellKey,
  rowLabel,
  type Citation,
  type ExtractionCell,
  type ExtractionTable,
  type MatchQuality,
  type PaperRow,
} from '@/lib/extraction';

import styles from './ReviewTable.module.css';

interface ReviewTableProps {
  table: ExtractionTable;
  /** `cellKey(documentId, columnKey)` of the citation currently open in the viewer. */
  activeCell?: string | null;
  onCitationSelect: (row: PaperRow, columnKey: string, cell: ExtractionCell) => void;
  /** Columns being generated right now, rendered as pending headers ahead of their values. */
  pendingColumns?: string[];
  busy?: boolean;
}

/** How each match quality is stated in plain words. */
const MATCH_WORDING: Record<MatchQuality, string> = {
  exact: 'the quoted words appear on the page exactly as shown',
  normalized: 'the quoted words appear on the page, with only spacing and line breaks differing',
  fuzzy: 'the passage is close but not word-for-word, so read it before relying on the value',
};

/**
 * What the citation means, in plain words, as the cell's tooltip. The precise locator (text
 * block id, raw match quality) lives in the viewer's technical details, one click away.
 */
function citationDetail(citation: Citation): string {
  return `Page ${citation.page_number}: ${MATCH_WORDING[citation.match]}. Click to see the passage highlighted on the page, with the exact locator under "Technical details".`;
}

function CellContent({
  row,
  columnKey,
  cell,
  active,
  onSelect,
}: {
  row: PaperRow;
  columnKey: string;
  cell: ExtractionCell | undefined;
  active: boolean;
  onSelect: ReviewTableProps['onCitationSelect'];
}) {
  if (!cell || cell.status === 'not_found' || !cell.value) {
    return (
      <span className={styles.missing}>
        —<span className={styles.note}>{cell?.note || 'Not reported in this paper'}</span>
      </span>
    );
  }

  if (cell.status === 'grounded' && cell.citation) {
    const { page_number: page, match } = cell.citation;
    // `normalized` only means whitespace was folded before matching, so it is as verified as
    // `exact`; only a fuzzy span is genuinely approximate and must be flagged.
    const approximate = match === 'fuzzy';
    return (
      <>
        <button
          type="button"
          className={[styles.cited, active ? styles.citedActive : ''].filter(Boolean).join(' ')}
          aria-pressed={active}
          aria-label={`Show source for ${rowLabel(row)}, page ${page}`}
          title={citationDetail(cell.citation)}
          onClick={() => onSelect(row, columnKey, cell)}
        >
          <span className={styles.value}>{cell.value}</span>
          <span className={approximate ? styles.pageRefFuzzy : styles.pageRef}>
            page {page}
            {approximate ? ', close wording' : ''}
          </span>
        </button>
        {/* Anything the extractor had to say about how it read this value stays on screen. */}
        {cell.note && <span className={styles.note}>{cell.note}</span>}
      </>
    );
  }

  // A value the model produced but could not ground in the parsed text: shown, never
  // silently dropped, but it must not look like a cited value.
  return (
    <span className={styles.unverified}>
      {cell.value}
      <span className={styles.unverifiedTag}>no source found</span>
      <span className={styles.note}>
        {cell.note || 'The value could not be traced to a passage in this paper.'}
      </span>
    </span>
  );
}

/** Row warnings, all of them: a paper with several parsing problems must not report one. */
function RowWarnings({ warnings }: { warnings: string[] }) {
  if (warnings.length === 0) return null;
  if (warnings.length === 1) return <> · {warnings[0]}</>;

  return (
    <>
      {' · '}
      <details className={styles.warnings}>
        <summary>{warnings.length} problems reading this paper</summary>
        <ul>
          {warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      </details>
    </>
  );
}

export function ReviewTable({
  table,
  activeCell,
  onCitationSelect,
  pendingColumns = [],
  busy = false,
}: ReviewTableProps) {
  const pending = pendingColumns.filter(
    (label) => !table.columns.some((column) => column.label === label),
  );

  return (
    <div className={styles.container}>
      {/* Only the grid scrolls sideways: the scroll box is its own flex item, so however many
          columns a goal produces it can never widen the panel or the page behind it. */}
      <div className={styles.scroll}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th scope="col" className={styles.paperHeader}>
                Paper
              </th>
              {table.columns.map((column) => (
                <th key={column.key} scope="col" title={column.description || column.label}>
                  {column.label}
                </th>
              ))}
              {pending.map((label) => (
                <th key={label} scope="col" className={styles.pendingHeader}>
                  {label}
                  <span className={styles.pendingBar} aria-hidden="true" />
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {table.rows.map((row) => (
              <tr key={row.document_id} data-status={row.status}>
                <th scope="row" className={styles.paperCell}>
                  <span className={styles.paperTitle} title={rowLabel(row)}>
                    {rowLabel(row)}
                  </span>
                  <span className={styles.paperMeta}>
                    {row.page_count > 0 ? `${row.page_count} pages` : 'no pages parsed'}
                    <RowWarnings warnings={row.warnings} />
                  </span>
                </th>
                {table.columns.map((column) => (
                  <td key={column.key}>
                    <CellContent
                      row={row}
                      columnKey={column.key}
                      cell={row.cells[column.key]}
                      active={activeCell === cellKey(row.document_id, column.key)}
                      onSelect={onCitationSelect}
                    />
                  </td>
                ))}
                {pending.map((label) => (
                  <td key={label}>
                    <span className={styles.skeleton} aria-hidden="true" />
                  </td>
                ))}
              </tr>
            ))}
            {busy && (
              <tr>
                <th scope="row" className={styles.paperCell}>
                  <span className={styles.skeleton} aria-hidden="true" />
                </th>
                {[...table.columns.map((column) => column.key), ...pending].map((key) => (
                  <td key={key}>
                    <span className={styles.skeleton} aria-hidden="true" />
                  </td>
                ))}
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {table.rows.length > 0 && (
        <div className={styles.legend}>
          <div className={styles.legendRow}>
            <span className={styles.legendItem}>
              <span className={styles.pageRef}>page 1</span> the quote is on page 1 of the PDF —
              click the value to read it
            </span>
            <span className={styles.legendItem}>
              <span className={styles.pageRefFuzzy}>page 1, close wording</span> the passage was
              found but is not word-for-word
            </span>
            <span className={styles.legendItem}>
              <span className={styles.unverifiedTag}>no source found</span> the value could not be
              traced to a passage — treat it as unchecked
            </span>
            {/* The precise vocabulary is one click away rather than deleted. */}
            <details className={styles.legendDetail}>
              <summary>How a quote is matched to a page (exact detail)</summary>
              <ul>
                <li>
                  <strong>exact</strong> — the extracted quote is character-for-character present
                  in the parsed page text.
                </li>
                <li>
                  <strong>normalized</strong> — it matches once runs of spaces, line breaks and
                  hyphenation are folded; shown the same as an exact match because the wording is
                  unchanged.
                </li>
                <li>
                  <strong>fuzzy</strong> — only a close match was found, shown as
                  &ldquo;close wording&rdquo;; the highlighted span is approximate.
                </li>
                <li>
                  Hovering a value shows its page number and the internal text-block reference (for
                  example <code>p1-b4</code> — block 4 on page 1) used to place the highlight.
                </li>
              </ul>
            </details>
          </div>
        </div>
      )}
    </div>
  );
}
