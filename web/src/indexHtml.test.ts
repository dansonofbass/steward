// web/index.html's head links the favicon set, the home-screen icon and the manifest (the mark: ui/markArt.ts).
import { existsSync, readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { PHASE_BG, type Phase } from './lib/sky';
import { DARK_SKY } from './lib/theme';
import { readCss, rules } from './test-css';

// The path goes through a plain variable so the bundler doesn't turn the URL into an asset link.
const at = (rel: string) => new URL(rel, import.meta.url);
const root = (rel: string) => at('../' + rel);
const html = readFileSync(root('index.html'), 'utf8');
const head = html.slice(0, html.indexOf('</head>'));
const tags = (name: string) => head.match(new RegExp(`<${name}\\b[^>]*>`, 'g')) ?? [];
const attr = (tag: string, a: string) => tag.match(new RegExp(`\\s${a}="([^"]*)"`))?.[1] ?? null;
const link = (rel: string) => tags('link').find((t) => attr(t, 'rel') === rel);

describe('index.html', () => {
  it('links the SVG favicon first, then the PNG fallbacks', () => {
    const icons = tags('link').filter((t) => attr(t, 'rel') === 'icon');
    expect(icons.map((t) => [attr(t, 'href'), attr(t, 'type'), attr(t, 'sizes')])).toEqual([
      ['/favicon.svg', 'image/svg+xml', null],
      ['/favicon-32.png', 'image/png', '32x32'],
      ['/favicon-16.png', 'image/png', '16x16'],
    ]);
  });

  it('links the apple-touch-icon and the manifest', () => {
    expect(attr(link('apple-touch-icon')!, 'href')).toBe('/apple-touch-icon.png');
    expect(attr(link('manifest')!, 'href')).toBe('/manifest.webmanifest');
  });

  it('sets one theme colour, which the first-paint script points at the phase on screen (phase 17, 2.6)', () => {
    const theme = tags('meta').filter((t) => attr(t, 'name') === 'theme-color');
    expect(theme.map((t) => [attr(t, 'media'), attr(t, 'content')])).toEqual([[null, '#FAF8F3']]);
    const map = /var bg = (\{[^}]*\});/.exec(head)?.[1] ?? '';
    expect(Object.fromEntries([...map.matchAll(/(\w+): '(#[0-9A-F]{6})'/g)].map((m) => [m[1], m[2]]))).toEqual(PHASE_BG);
    expect(head).toContain(`document.querySelector('meta[name="theme-color"]').setAttribute('content', bg[phase]);`);
  });

  it("the first paint follows the sky's dark half on a device set to dark, as lib/theme does (WEB-10)", () => {
    const map = /var darkSky = (\{[^}]*\});/.exec(head)?.[1] ?? '';
    expect(Object.fromEntries([...map.matchAll(/(\w+): '(\w+)'/g)].map((m) => [m[1], m[2]]))).toEqual(DARK_SKY);
    expect(head).toContain("window.matchMedia('(prefers-color-scheme: dark)').matches) p = darkSky[p];");
  });

  it("lib/sky PHASE_BG is each phase's --bg in sky.css", () => {
    const seen: string[] = [];
    for (const r of rules(readCss('styles/sky.css'))) {
      const phase = r.sel.map((s) => /data-phase="(\w+)"/.exec(s)?.[1]).find(Boolean) as Phase | undefined;
      if (!phase) continue;
      seen.push(phase);
      expect(r.body, phase).toContain(`--bg: ${PHASE_BG[phase]};`);
    }
    expect(seen.sort()).toEqual(Object.keys(PHASE_BG).sort());
  });

  it('points only at files that exist in public/', () => {
    const hrefs = tags('link').map((t) => attr(t, 'href')).filter((h): h is string => !!h && h.startsWith('/'));
    expect(hrefs.length).toBe(5);
    for (const h of hrefs) expect(existsSync(root(`public${h}`)), h).toBe(true);
  });
});

describe('manifest.webmanifest', () => {
  const m = JSON.parse(readFileSync(root('public/manifest.webmanifest'), 'utf8'));

  it('names Steward and sets its colours and display', () => {
    expect(m).toMatchObject({ name: 'Steward', short_name: 'Steward', theme_color: '#7C3352', background_color: '#FAF8F3', display: 'standalone' });
  });

  it('lists the 192 and 512 icons, and a maskable 512, each a file in public/', () => {
    expect(m.icons.map((i: { src: string; sizes: string; purpose: string }) => [i.src, i.sizes, i.purpose])).toEqual([
      ['/icon-192.png', '192x192', 'any'],
      ['/icon-512.png', '512x512', 'any'],
      ['/icon-512-maskable.png', '512x512', 'maskable'],
    ]);
    for (const i of m.icons) expect(existsSync(root(`public${i.src}`)), i.src).toBe(true);
  });
});
