import { describe, expect, it } from 'vitest';

import { safeHref } from './links';

describe('safeHref', () => {
  it('keeps the schemes a paper or a record is served over', () => {
    expect(safeHref('https://pubmed.ncbi.nlm.nih.gov/12345/')).toBe(
      'https://pubmed.ncbi.nlm.nih.gov/12345/',
    );
    expect(safeHref('http://example.org/paper.pdf')).toBe('http://example.org/paper.pdf');
    expect(safeHref('mailto:security@askgrey.app')).toBe('mailto:security@askgrey.app');
  });

  it('drops a scheme that would run as script or read the disk', () => {
    // A source URL arrives from a colleague's saved workspace or a third-party API, so an
    // href is caller-supplied text.
    expect(safeHref('javascript:alert(document.cookie)')).toBeUndefined();
    expect(safeHref('  JaVaScRiPt:alert(1)')).toBeUndefined();
    expect(safeHref('data:text/html,<script>alert(1)</script>')).toBeUndefined();
    expect(safeHref('file:///etc/passwd')).toBeUndefined();
  });

  it('passes our own routes and anchors through', () => {
    expect(safeHref('/literature')).toBe('/literature');
    expect(safeHref('#review-first')).toBe('#review-first');
  });

  it('has nothing to render for an empty or missing url', () => {
    expect(safeHref('')).toBeUndefined();
    expect(safeHref(null)).toBeUndefined();
    expect(safeHref(undefined)).toBeUndefined();
    expect(safeHref('not a url at all')).toBeUndefined();
  });
});
