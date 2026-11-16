// The welcome, the Help page and the Sample book are lazy chunks (bundle-size.mjs budgets them): nothing in the first
// download imports them statically. The Sample folder joins when it exists (Task 10).
import { describe, expect, it } from 'vitest';
import { readdirSync, readFileSync } from 'node:fs';

const src = (rel: string) => new URL(rel, import.meta.url);
const STATIC = /^\s*(?:import|export)\b[^;'"()]*?(?:from\s*)?['"]([^'"]+)['"]/gm;
const LAZY = /screens\/welcome|\.\/welcome\/|\.\.\/welcome\/|screens\/you\/Help|\.\/Help$|book\/sample|\.\/sample\//;
const lazyImports = (code: string) => [...code.matchAll(STATIC)].map((m) => m[1]).filter((p) => LAZY.test(p));
const FILES = readdirSync(src('../../'), { recursive: true, encoding: 'utf8' })
  .filter((f) => /\.tsx?$/.test(f) && !/\.test\.tsx?$/.test(f)
    && !f.startsWith('screens/welcome/') && !f.startsWith('book/sample/') && f !== 'screens/you/Help.tsx');

describe('the welcome, Help and the Sample stay out of the first download', () => {
  it('catches a static import of them (the check works)', () => {
    expect(lazyImports("import Welcome from './screens/welcome/Welcome';")).toHaveLength(1);
    expect(lazyImports("import Help from './Help';")).toHaveLength(1);
    expect(lazyImports("const Welcome = lazyScreen(() => import('./screens/welcome/Welcome'));")).toEqual([]);
  });
  it('is imported statically by nothing outside their own folders', () => {
    expect(FILES).toContain('routes.tsx');
    for (const f of FILES) expect([f, lazyImports(readFileSync(src(`../../${f}`), 'utf8'))]).toEqual([f, []]);
  });
});
