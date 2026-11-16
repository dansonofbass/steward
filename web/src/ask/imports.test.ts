// P26 (Engineering choice 3): the Ask button and the ask/ store are in the first download, so they import nothing from
// screens/chat statically. The panel loads through ask/panel.ts's dynamic import(), which Vite splits.
import { describe, expect, it } from 'vitest';
import { readdirSync, readFileSync } from 'node:fs';

const src = (rel: string) => new URL(rel, import.meta.url);
const STATIC = /^\s*(?:import|export)\b[^;'"()]*?(?:from\s*)?['"]([^'"]+)['"]/gm;
const chatImports = (code: string) => [...code.matchAll(STATIC)].map((m) => m[1]).filter((p) => /screens\/chat/.test(p));
const FILES = ['../ui/AskAbout.tsx', ...readdirSync(src('./'), { recursive: true, encoding: 'utf8' })
  .filter((f) => /\.tsx?$/.test(f) && !/\.test\.tsx?$/.test(f)).map((f) => `./${f}`)];

describe('the eager Ask pieces', () => {
  it('catch a static import of screens/chat (the check works)', () => {
    expect(chatImports("import { Composer } from '../screens/chat/Composer';\nexport { x } from '../screens/chat/x';")).toHaveLength(2);
    expect(chatImports("export const AskPanel = lazyScreen(() => import('../screens/chat/panel/AskPanel'));")).toEqual([]);
  });
  it('never import screens/chat statically', () => {
    expect(FILES).toContain('./store.ts');
    for (const f of FILES) expect([f, chatImports(readFileSync(src(f), 'utf8'))]).toEqual([f, []]);
  });
});
