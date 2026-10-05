import { readFileSync } from 'node:fs';
import path from 'node:path';

import { describe, expect, it } from 'vitest';

/**
 * The layout contract that keeps an extraction run readable.
 *
 * jsdom has no layout engine, so the only place this can be checked without a browser is the
 * stylesheet. Both halves of it were broken in the same run: a short panel squeezed the grid
 * until its legend printed over the export row, and a long value sat beside a page reference
 * that could not wrap until it ran into the next column.
 */
const PAGE_CSS = readFileSync(path.resolve(__dirname, 'LiteraturePage.module.css'), 'utf8');
const TABLE_CSS = readFileSync(
  path.resolve(__dirname, '..', 'components', 'ReviewTable.module.css'),
  'utf8',
);

function rule(css: string, selector: string): string {
  const match = css.match(new RegExp(`\\${selector}\\s*\\{([^}]*)\\}`));
  expect(match, `${selector} is missing`).not.toBeNull();
  return match?.[1] ?? '';
}

describe('literature run layout', () => {
  it('scrolls the canvas instead of compressing the table out of its box', () => {
    expect(rule(PAGE_CSS, '.canvas')).toMatch(/overflow-y:\s*auto/);
  });

  it('holds the table above a floor, so its legend is never laid out past its edge', () => {
    const container = rule(TABLE_CSS, '.container');
    expect(container).toMatch(/min-height:\s*min-content/);

    const scroll = rule(TABLE_CSS, '.scroll');
    expect(scroll).toMatch(/min-height:\s*\d/);
    expect(scroll).toMatch(/overflow:\s*auto/);
  });

  it('wraps a cited value and its page reference instead of letting them leave the cell', () => {
    const cited = rule(TABLE_CSS, '.cited');
    expect(cited).toMatch(/flex-wrap:\s*wrap/);
    expect(cited).toMatch(/max-width:\s*100%/);
  });
});
