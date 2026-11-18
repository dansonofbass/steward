// Issue #25: the two above-the-fold faces are preloaded (scripts/preload-fonts.ts), and while a web font loads, the
// fallback is sized to it, so the swap doesn't reflow Home's headline.
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { ABOVE_THE_FOLD, fontPreloads } from '../../scripts/preload-fonts';

const read = (rel: string) => readFileSync(new URL(rel, import.meta.url), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
const FILES = [
  'assets/index-Ab12.js', 'assets/newsreader-latin-wght-normal-Cx9_2kQe.woff2', 'assets/newsreader-latin-ext-wght-normal-Q1.woff2',
  'assets/source-sans-3-latin-400-normal-Df-3.woff2', 'assets/source-sans-3-latin-600-normal-Z.woff2', 'assets/source-sans-3-latin-ext-400-normal-Y.woff2',
];

describe('the font preloads (issue #25)', () => {
  it("preload exactly Newsreader's latin variable face and Source Sans 3's latin 400, as fonts, with crossorigin", () => {
    expect(fontPreloads(FILES, '/')).toEqual([
      { tag: 'link', attrs: { rel: 'preload', href: '/assets/newsreader-latin-wght-normal-Cx9_2kQe.woff2', as: 'font', type: 'font/woff2', crossorigin: true }, injectTo: 'head' },
      { tag: 'link', attrs: { rel: 'preload', href: '/assets/source-sans-3-latin-400-normal-Df-3.woff2', as: 'font', type: 'font/woff2', crossorigin: true }, injectTo: 'head' },
    ]);
  });

  it('fail the build when a face is missing or matched twice', () => {
    expect(() => fontPreloads(FILES.filter((f) => !f.includes('newsreader-latin-wght')), '/')).toThrow(/0 files match/);
    expect(() => fontPreloads([...FILES, 'assets/source-sans-3-latin-400-normal-Other.woff2'], '/')).toThrow(/2 files match/);
    expect(ABOVE_THE_FOLD).toHaveLength(2);
  });
});

describe('the size-matched fallbacks (issue #25)', () => {
  const css = read('./fonts.css');
  const faces = [...css.matchAll(/@font-face\s*\{([^}]*)\}/g)].map((m) => m[1]);
  const family = (body: string) => /font-family:\s*'([^']+)'/.exec(body)![1];

  it('give every fallback face a size, ascent, descent and line-gap override, from a local font', () => {
    expect(faces.length).toBeGreaterThanOrEqual(4);
    for (const f of faces) {
      expect(f, family(f)).toMatch(/src:\s*local\('/);
      for (const d of ['size-adjust', 'ascent-override', 'descent-override', 'line-gap-override']) expect(f, `${family(f)} ${d}`).toMatch(new RegExp(`${d}:\\s*[\\d.]+%`));
    }
  });

  it('put the fallback faces right after the web font in both stacks', () => {
    const tokens = read('./tokens.css');
    const stack = (name: string) => new RegExp(`${name}:\\s*([^;]+);`).exec(tokens)![1].split(',').map((s) => s.trim().replace(/'/g, ''));
    const fallbacks = faces.map(family);
    const body = stack('--font');
    expect(body[0]).toBe('Source Sans 3');
    expect(body.slice(1, 4)).toEqual(fallbacks.filter((f) => f.startsWith('Source Sans 3 fallback')));
    const display = stack('--font-display');
    expect(display.slice(0, 2)).toEqual(['Newsreader Variable', 'Newsreader']);
    expect(display.slice(2, 4)).toEqual(fallbacks.filter((f) => f.startsWith('Newsreader fallback')));
  });
});
