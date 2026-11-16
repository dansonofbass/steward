// WEB-2 and 16i review Minor 4: ScrollRestoration (RouteFrame) puts a new page at its top. A change of the query on the
// same page (a filter, a span, a dropped one-time parameter) isn't a new page, so every setter from useSearchParams
// passes preventScrollReset. A scan of every source fails on one that doesn't.
import { describe, expect, it } from 'vitest';

const SOURCES: Record<string, string> = Object.fromEntries(
  Object.entries(import.meta.glob<string>('/src/**/*.tsx', { query: '?raw', import: 'default', eager: true }))
    .filter(([path]) => !/\.test\.[jt]sx?$/.test(path)),
);

/** The text of a call that starts at `at` ("name(" ...), up to its closing parenthesis. */
function callAt(src: string, at: number): string {
  let depth = 0;
  for (let i = src.indexOf('(', at); i < src.length; i++) {
    if (src[i] === '(') depth++;
    else if (src[i] === ')' && --depth === 0) return src.slice(at, i + 1);
  }
  return src.slice(at);
}

function problems(sources: Record<string, string>): { setters: number; problems: string[] } {
  const out: string[] = [];
  let setters = 0;
  for (const [path, src] of Object.entries(sources)) {
    for (const m of src.matchAll(/const \[\w+, (\w+)\] = useSearchParams\(\)/g)) {
      const setter = m[1];
      for (const call of src.matchAll(new RegExp(`\\b${setter}\\(`, 'g'))) {
        setters++;
        if (!/preventScrollReset: true/.test(callAt(src, call.index!))) out.push(`${path}: ${setter}(…) without preventScrollReset`);
      }
    }
  }
  return { setters, problems: out };
}

describe('a query change on the same page keeps its scroll (WEB-2)', () => {
  it('every useSearchParams setter passes preventScrollReset', () => {
    const { setters, problems: found } = problems(SOURCES);
    expect(setters).toBeGreaterThanOrEqual(9);
    expect(found).toEqual([]);
  });

  it('catches a setter without it', () => {
    const planted = { '/src/a.tsx': "const [sp, setSp] = useSearchParams();\nsetSp({ months: '6' }, { replace: true });" };
    expect(problems(planted).problems).toEqual(['/src/a.tsx: setSp(…) without preventScrollReset']);
  });
});
