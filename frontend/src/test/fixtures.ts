import type {
  Citation,
  ExtractionCell,
  ExtractionTable,
  MatchQuality,
  PaperRow,
} from '@/lib/extraction';

export function citation(overrides: Partial<Citation> = {}): Citation {
  return {
    document_id: 'doc-1',
    source_url: 'https://example.org/paper.pdf',
    page_number: 4,
    page_width: 612,
    page_height: 792,
    block_id: 'p4-b2',
    text: '73 patients were randomized to ziprasidone or placebo',
    start_char: 120,
    end_char: 173,
    bbox: { x0: 72, top: 300, x1: 520, bottom: 316 },
    rects: [{ x0: 72, top: 300, x1: 520, bottom: 316 }],
    match: 'exact',
    ...overrides,
  };
}

export function grounded(value: string, match: MatchQuality = 'exact'): ExtractionCell {
  return { value, citation: citation({ match }), status: 'grounded', note: '' };
}

export function ungrounded(value: string): ExtractionCell {
  return { value, citation: null, status: 'ungrounded', note: 'quote not found in parsed text' };
}

export function notFound(): ExtractionCell {
  return { value: null, citation: null, status: 'not_found', note: '' };
}

export function paperRow(overrides: Partial<PaperRow> = {}): PaperRow {
  return {
    document_id: 'doc-1',
    title: 'Ziprasidone in acute mania',
    source_url: 'https://example.org/paper.pdf',
    filename: 'paper.pdf',
    page_count: 9,
    status: 'extracted',
    cells: {},
    warnings: [],
    ...overrides,
  };
}

export function table(overrides: Partial<ExtractionTable> = {}): ExtractionTable {
  return {
    goal: 'sample size',
    columns: [{ key: 'sample_size', label: 'sample size', description: '' }],
    rows: [paperRow({ cells: { sample_size: grounded('73 patients') } })],
    ...overrides,
  };
}
