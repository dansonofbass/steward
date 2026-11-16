// WEB-19 (release gate 0.1.0, fix 16i): screens that are opened rarely stay out of the first download. This walks the
// static import graph from main.tsx (import() is a chunk boundary and type-only imports are erased) and fails if one
// of them is reachable again; scripts/bundle-size.mjs then measures what's left.
import { existsSync as exists, readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

// Paths are relative to src/, where this file is. The path goes through a function so the bundler doesn't turn the
// URL into an asset link.
const at = (rel: string) => new URL(rel, import.meta.url);
const read = (rel: string) => readFileSync(at(rel), 'utf8');
const existsSync = (rel: string) => exists(at(rel));
const dirname = (rel: string) => (rel.includes('/') ? rel.slice(0, rel.lastIndexOf('/')) : '');
/** dir + a relative specifier, with . and .. resolved. */
function join(dir: string, spec: string): string {
  const parts: string[] = dir ? dir.split('/') : [];
  for (const p of spec.split('/')) {
    if (p === '..') parts.pop();
    else if (p !== '.' && p !== '') parts.push(p);
  }
  return parts.join('/');
}
const STATIC = /^\s*(import|export)\s+(?!type\b)[^;]*?\bfrom\s*['"]([^'"]+)['"]|^\s*import\s+['"]([^'"]+)['"]/gm;

/** The relative source files a file imports statically, as paths under src/. */
function importsOf(rel: string): string[] {
  const out: string[] = [];
  for (const m of read(rel).matchAll(STATIC)) {
    const spec = m[2] ?? m[3];
    if (!spec?.startsWith('.')) continue;
    const base = join(dirname(rel), spec);
    const hit = [base, `${base}.ts`, `${base}.tsx`, `${base}/index.ts`, `${base}/index.tsx`].find((p) => /\.tsx?$/.test(p) && existsSync(p));
    if (hit) out.push(hit);
  }
  return out;
}

function firstDownload(): Set<string> {
  const seen = new Set<string>();
  const walk = (f: string) => { if (seen.has(f)) return; seen.add(f); importsOf(f).forEach(walk); };
  walk('main.tsx');
  return seen;
}

/** Out of the first download, each loaded when it opens. */
const LAZY = [
  'screens/Settings.tsx', 'screens/settings/Members.tsx', 'screens/settings/Banks.tsx', 'screens/settings/CategoryRules.tsx',
  'screens/settings/Log.tsx', 'screens/settings/Books.tsx', 'screens/settings/BookDetails.tsx', 'screens/settings/ThisBook.tsx',
  'screens/you/SignInDevices.tsx', 'screens/you/AppearancePage.tsx', 'screens/Invite.tsx', 'screens/Forgot.tsx', 'screens/Reset.tsx',
  'ui/CopyButton.tsx',
];

describe('the first download (WEB-19)', () => {
  const entry = firstDownload();

  it('reaches the shell, and the walk sees through imports', () => {
    for (const f of ['App.tsx', 'routes.tsx', 'ui/Sheet.tsx', 'ui/Field.tsx', 'frame/RouteFrame.tsx', 'screens/settings/sections.ts', 'screens/Login.tsx']) {
      expect(entry, f).toContain(f);
    }
    expect(entry.size).toBeGreaterThan(100);
  });

  it('leaves out the screens opened rarely', () => {
    for (const f of LAZY) expect(existsSync(f), f).toBe(true);
    expect(LAZY.filter((f) => entry.has(f))).toEqual([]);
  });

  it('a static import counts, an import() and a type-only import do not', () => {
    const specs = (code: string) => [...code.matchAll(STATIC)].map((m) => m[2] ?? m[3]);
    expect(specs("import Settings from './screens/Settings';")).toEqual(['./screens/Settings']);
    expect(specs("export { X } from './x';")).toEqual(['./x']);
    expect(specs("import './styles/base.css';")).toEqual(['./styles/base.css']);
    expect(specs("const S = lazyScreen(() => import('./screens/Settings'));")).toEqual([]);
    expect(specs("import type { Me } from './api/types';")).toEqual([]);
  });
});
