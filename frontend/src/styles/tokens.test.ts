import { readFileSync, readdirSync } from 'node:fs';
import path from 'node:path';

import { describe, expect, it } from 'vitest';

const SRC_DIR = path.resolve(__dirname, '..');
const TOKENS_FILE = path.join(SRC_DIR, 'styles', 'tokens.css');

/** Hex colours, plus rgb()/hsl() with literal channel values. */
const LITERAL_COLOUR = /#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?)\(\s*\d/;

function collectCssFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return collectCssFiles(full);
    return entry.isFile() && entry.name.endsWith('.css') ? [full] : [];
  });
}

describe('design tokens', () => {
  it('defines every documented colour, type and layout token', () => {
    const tokens = readFileSync(TOKENS_FILE, 'utf8');
    const required = [
      '--color-surface-workspace',
      '--color-surface-panel',
      '--color-text-primary',
      '--color-border-default',
      '--color-accent-pipeline',
      '--color-accent-warning',
      '--color-accent-success',
      '--font-family-display',
      '--font-size-xs',
      '--line-height-dense',
      '--space-4',
      '--layout-sidebar-width',
      '--layout-sidebar-width-collapsed',
    ];
    for (const token of required) {
      expect(tokens, `${token} is missing from tokens.css`).toContain(`${token}:`);
    }
  });

  it('keeps literal colours out of component stylesheets', () => {
    const offenders = collectCssFiles(SRC_DIR)
      .filter((file) => file !== TOKENS_FILE)
      .flatMap((file) =>
        readFileSync(file, 'utf8')
          .split('\n')
          .map((line, index) => ({ file, line, number: index + 1 }))
          .filter(({ line }) => LITERAL_COLOUR.test(line))
          // rgb(0 0 0 / n%) inside shadow tokens is the one sanctioned exception, and it
          // only ever appears in tokens.css, which is already excluded above.
          .map(({ file, number, line }) => `${path.relative(SRC_DIR, file)}:${number} ${line.trim()}`),
      );

    expect(offenders, 'use a var(--color-*) token instead of a literal colour').toEqual([]);
  });
});
