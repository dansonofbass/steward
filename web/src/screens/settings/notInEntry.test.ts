// Settings is its own chunk now (WEB-19, entryGraph.test.ts), and its sheets behind a click are lazy chunks of their own (guided setup spec 11): the invite
// sheet with its email-off words, the add-a-book sheet and the SimpleFIN link form. Only lazy screens (the welcome, Get
// Steward ready) and the sheets themselves import them statically.
import { describe, expect, it } from 'vitest';
import { readdirSync, readFileSync } from 'node:fs';

const src = (rel: string) => new URL(rel, import.meta.url);
const STATIC = /^\s*(?:import|export)\b[^;'"()]*?(?:from\s*)?['"]([^'"]+)['"]/gm;
const LAZY = /(?:^|\/)(?:InviteSheet|AddBookSheet|LinkForm|inviteCopy)$/;
const lazyImports = (code: string) => [...code.matchAll(STATIC)].map((m) => m[1]).filter((p) => LAZY.test(p));
const OWN = new Set(['screens/settings/InviteSheet.tsx', 'screens/settings/AddBookSheet.tsx', 'screens/settings/LinkForm.tsx']);
const FILES = readdirSync(src('../../'), { recursive: true, encoding: 'utf8' })
  .filter((f) => /\.tsx?$/.test(f) && !/\.test\.tsx?$/.test(f)
    && !f.startsWith('screens/welcome/') && !f.startsWith('screens/ready/') && !OWN.has(f));

describe("Settings' sheets stay out of the first download", () => {
  it('catches a static import of them (the check works)', () => {
    expect(lazyImports("import { InviteSheet } from './InviteSheet';")).toHaveLength(1);
    expect(lazyImports("import { AddBookSheet } from '../settings/AddBookSheet';")).toHaveLength(1);
    expect(lazyImports("import { LinkForm } from './LinkForm';")).toHaveLength(1);
    expect(lazyImports("export { COPY } from '../settings/inviteCopy';")).toHaveLength(1);
    expect(lazyImports("const InviteSheet = lazyScreen(() => import('./InviteSheet'));")).toEqual([]);
  });
  it('is imported statically by nothing in the first download', () => {
    expect(FILES).toContain('screens/settings/Members.tsx');
    for (const f of FILES) expect([f, lazyImports(readFileSync(src(`../../${f}`), 'utf8'))]).toEqual([f, []]);
  });
});
