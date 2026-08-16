import { describe, expect, it } from 'vitest';

import { grounded, notFound, paperRow, table } from '@/test/fixtures';

import { EMPTY_TABLE, cellKey, groundedCount, mergeTables, rowLabel } from './extraction';

describe('mergeTables', () => {
  it('appends a new goal as extra columns on the rows already in the table', () => {
    const first = table();
    const second = table({
      goal: 'dosing regimen',
      columns: [{ key: 'dosing_regimen', label: 'dosing regimen', description: '' }],
      rows: [paperRow({ cells: { dosing_regimen: grounded('40-160 mg/d') } })],
    });

    const merged = mergeTables(first, second);

    expect(merged.columns.map((column) => column.key)).toEqual(['sample_size', 'dosing_regimen']);
    expect(merged.rows).toHaveLength(1);
    expect(merged.rows[0].cells.sample_size.value).toBe('73 patients');
    expect(merged.rows[0].cells.dosing_regimen.value).toBe('40-160 mg/d');
    expect(merged.goal).toBe('sample size; dosing regimen');
  });

  it('adds a second paper as a new row under the same columns', () => {
    const merged = mergeTables(
      table(),
      table({
        rows: [
          paperRow({
            document_id: 'doc-2',
            title: 'Second trial',
            cells: { sample_size: grounded('210 patients') },
          }),
        ],
      }),
    );

    expect(merged.rows.map((row) => row.document_id)).toEqual(['doc-1', 'doc-2']);
    expect(merged.goal).toBe('sample size');
  });

  it('re-running the same goal over the same paper replaces its cells rather than duplicating', () => {
    const rerun = table({ rows: [paperRow({ cells: { sample_size: notFound() } })] });

    const merged = mergeTables(table(), rerun);

    expect(merged.rows).toHaveLength(1);
    expect(merged.rows[0].cells.sample_size.status).toBe('not_found');
  });

  it('starts from the empty table without inventing a goal', () => {
    expect(mergeTables(EMPTY_TABLE, table()).columns).toHaveLength(1);
    expect(mergeTables(EMPTY_TABLE, table()).goal).toBe('sample size');
  });
});

describe('helpers', () => {
  it('counts only grounded cells', () => {
    expect(groundedCount(table())).toBe(1);
    expect(groundedCount(table({ rows: [paperRow({ cells: { sample_size: notFound() } })] }))).toBe(
      0,
    );
  });

  it('falls back from title to filename to id', () => {
    expect(rowLabel(paperRow({ title: '', filename: 'trial.pdf' }))).toBe('trial.pdf');
    expect(rowLabel(paperRow({ title: '', filename: '' }))).toBe('doc-1');
  });

  it('keys a cell by document and column', () => {
    expect(cellKey('doc-1', 'sample_size')).toBe('doc-1::sample_size');
  });
});
