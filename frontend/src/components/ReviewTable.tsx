import { cellKey, rowLabel, type ExtractionCell, type ExtractionTable, type PaperRow } from '@/lib/extraction';

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
      <span className={styles.missing} title={cell?.note || 'Not found in this paper'}>
        —
      </span>
    );
  }

  if (cell.status === 'grounded' && cell.citation) {
    const { page_number: page, match } = cell.citation;
    // `normalized` only means whitespace was folded before matching, so it is as verified as
    // `exact`; only a fuzzy span is genuinely approximate and must be flagged.
    const approximate = match === 'fuzzy';
    return (
      <button
        type="button"
        className={[styles.cited, active ? styles.citedActive : ''].filter(Boolean).join(' ')}
        aria-pressed={active}
        aria-label={`Show source for ${rowLabel(row)}, page ${page}`}
        onClick={() => onSelect(row, columnKey, cell)}
      >
        <span className={styles.value}>{cell.value}</span>
        <span className={approximate ? styles.pageRefFuzzy : styles.pageRef}>
          p{page}
          {approximate ? '~' : ''}
        </span>
      </button>
    );
  }

  // A value the model produced but could not ground in the parsed text: shown, never
  // silently dropped, but it must not look like a cited value.
  return (
    <span className={styles.unverified} title={cell.note || 'No matching passage found'}>
      {cell.value}
      <span className={styles.unverifiedTag}>unverified</span>
    </span>
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
                <span className={styles.paperTitle}>{rowLabel(row)}</span>
                <span className={styles.paperMeta}>
                  {row.page_count > 0 ? `${row.page_count} pages` : 'no pages parsed'}
                  {row.warnings.length > 0 ? ` · ${row.warnings[0]}` : ''}
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
  );
}
