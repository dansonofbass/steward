// Get Steward ready is a lazy chunk (bundle-size.mjs budgets it): nothing in the first download imports it statically.
// The Chat settings page is itself a lazy chunk, so it may carry the pairing form.
import { describe, expect, it } from 'vitest';
import { readdirSync, readFileSync } from 'node:fs';

const src = (rel: string) => new URL(rel, import.meta.url);
const STATIC = /^\s*(?:import|export)\b[^;'"()]*?(?:from\s*)?['"]([^'"]+)['"]/gm;
const READY = /screens\/ready|\.\/ready\/|\.\.\/ready\//;
const readyImports = (code: string) => [...code.matchAll(STATIC)].map((m) => m[1]).filter((p) => READY.test(p));
const FILES = readdirSync(src('../../'), { recursive: true, encoding: 'utf8' })
  .filter((f) => /\.tsx?$/.test(f) && !/\.test\.tsx?$/.test(f) && !f.startsWith('screens/ready/') && !f.startsWith('screens/welcome/') && f !== 'screens/chat/ChatSettings.tsx');

describe('Get Steward ready stays out of the first download', () => {
  it('catches a static import of it (the check works)', () => {
    expect(readyImports("import { PairForm } from '../ready/PairForm';")).toHaveLength(1);
    expect(readyImports("const ReadyPage = lazyScreen(() => import('./ready/Ready'));")).toEqual([]);
  });
  it('is imported statically by nothing outside screens/ready', () => {
    expect(FILES).toContain('screens/Settings.tsx');
    for (const f of FILES) expect([f, readyImports(readFileSync(src(`../../${f}`), 'utf8'))]).toEqual([f, []]);
  });
});
