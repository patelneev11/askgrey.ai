import { describe, expect, it } from 'vitest';

import { TAB_INTROS } from './tab-intros';

/**
 * The tour and the per-tab notices are a second surface describing the first one, and they drift:
 * Workspace and Settings stopped being sample records while their notices still called them
 * "a sample record and read-only", so a new user was told their own account was invented.
 * These strings are the claims the app no longer makes anywhere.
 */
const RETRACTED = [
  /sample record/i,
  /read-only preview/i,
  /marked sample data/i,
  /\bmembers, roles\b/i,
  /\bseats and connected systems\b/i,
  /for everyone in the workspace/i,
];

describe('tab intros', () => {
  it('covers every tab once', () => {
    const ids = TAB_INTROS.map((intro) => intro.id);
    expect(new Set(ids).size).toBe(ids.length);
    expect(ids).toHaveLength(8);
  });

  it('makes no claim the pages themselves have retracted', () => {
    for (const intro of TAB_INTROS) {
      const copy = [intro.title, ...intro.body, intro.caveat ?? ''].join(' ');
      for (const claim of RETRACTED) {
        expect(copy, `${intro.id} intro`).not.toMatch(claim);
      }
    }
  });

  // The notice is what a user accepts on a surface whose numbers are approximations; dropping it
  // from those tabs is the regression this guards.
  it('keeps a reliability caveat on the tabs whose output is model-generated', () => {
    const caveated = TAB_INTROS.filter((intro) => intro.caveat).map((intro) => intro.id);
    expect(caveated).toEqual(['literature', 'screening', 'protocol', 'regulatory', 'grants']);
  });
});
