
// Generates src/styles/sky.css: one block of Steward colour tokens per sky phase.
// The phase table mirrors the author's sky clock (custom-theme/assets/js/sky/clock.js) at commit 0276c26 (2026-10-12),
// palette fields only (sky, t1, t2, lush, fig, mode). The token mapping follows that file's letterVars():
//   --bg          paper: dark ? mix(sky0, sky1, .35) : mix(sky2, white, .55); the day phase uses the design-pass
//                 spec's #FAF8F3 (site.css's own default paper), see docs/superpowers/specs/2026-10-13-steward-m1c-design-pass.md
//   --surface     raised: dark ? mix(sky1, sky0, .3) : white (night: DARK below)
//   --surface-2   the blog's chip as a solid colour: dark phases white 7% over the surface, light phases rgba(30,60,90,.06)
//                 over the paper; strengthened until it is at least GAP from --surface (see chipFor) (night: DARK below)
//   --ink/--ink-muted  t1 / t2;  --line  t1 at 14% (24% in dark phases, phase 17)
//   --accent      the FILL: light phases fig; dark phases (phase 17, D7) a deep plum with white text (--accent-ink #FFFFFF)
//   --accent-text the plum that reads as text and lines (links, the current tab, Undo, the focus ring, chart lines):
//                 light phases = --accent; dark phases a light plum (DARK below), through the floor.  --focus = --accent-text
//   --chart-out   money-out marks: light phases = --ink-muted; dark phases a quieter blue-grey, so money in leads
//   --track       under a progress fill: light phases = --surface-2; dark phases apart from both --bg and --surface
//   --line-strong a form field's edge (ruling R3): the least step from --surface toward t1 that reads at 3:1 on --bg and
//                 --surface, in every phase (--line stays decorative)
//   --money-in    lush;  --warn  glow amber #E6A23C (dark phases: the amber lifted toward white by .25)
//   --danger      a muted red per mode
//   text colours (ink, ink-muted, accent-text, money-in, warn, danger) get a legibility floor: 4.5:1 on bg, surface and surface-2
// src/styles/sky.contrast.test.ts pins every phase 17 target.
// Run: node scripts/make-sky.mjs   (do not edit sky.css by hand);  node scripts/make-sky.mjs --check  says whether it is current
import { readFileSync, writeFileSync } from 'node:fs';

const P = {
  night:    { mode: 1, sky: ['#0B1220', '#14203A', '#21384A'], t1: '#EEF1EC', t2: '#AEB9BF', lush: '#33673F', fig: '#5A2C40' },
  dawn:      { mode: 1, sky: ['#1B2740', '#4D5C78', '#C99C88'], t1: '#F4F0EA', t2: '#D0CED0', lush: '#41794A', fig: '#6A3346' },
  sunrise:   { mode: 0, sky: ['#9DB2C8', '#E2BCA4', '#F5D8B8'], t1: '#1E2226', t2: '#3B4148', lush: '#5BA452', fig: '#7A3550' },
  morning:   { mode: 0, sky: ['#9EC1DE', '#CFE0EC', '#F2EEE4'], t1: '#18222B', t2: '#3F4D59', lush: '#4AA846', fig: '#7C3352' },
  day:       { mode: 0, sky: ['#A6C9E5', '#DCE9F3', '#F5F3EC'], t1: '#17212A', t2: '#42505C', lush: '#43AB44', fig: '#7C3352' },
  afternoon: { mode: 0, sky: ['#9CB9D3', '#D8DED9', '#F0E2C8'], t1: '#1F2124', t2: '#3F3E3C', lush: '#56A647', fig: '#80344F' },
  evening:   { mode: 0, sky: ['#93A8BE', '#D9AC86', '#EFC390'], t1: '#1C1D21', t2: '#37332F', lush: '#6AA040', fig: '#823A48' },
  dusk:      { mode: 1, sky: ['#1C2436', '#454A5E', '#A9654C'], t1: '#F4EEE6', t2: '#C7BEB5', lush: '#426E3E', fig: '#5E2C3C' },
};
const ORDER = ['night', 'dawn', 'sunrise', 'morning', 'day', 'afternoon', 'evening', 'dusk'];

const h2r = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
const r2h = (r) => '#' + r.map((v) => Math.round(Math.max(0, Math.min(255, v))).toString(16).padStart(2, '0')).join('').toUpperCase();
const mix = (a, b, t) => { const A = h2r(a), B = h2r(b); return r2h(A.map((v, i) => v + (B[i] - v) * t)); };
const over = (rgb, alpha, base) => { const B = h2r(base); return r2h(B.map((v, i) => v + (rgb[i] - v) * alpha)); };
const rgba = (h, a) => `rgba(${h2r(h).join(', ')}, ${a})`;
const lum = (h) => { const [r, g, b] = h2r(h).map((v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }); return 0.2126 * r + 0.7152 * g + 0.0722 * b; };
export const contrast = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((m, n) => n - m); return (x + 0.05) / (y + 0.05); };
// Legibility floor: every colour used for text is moved the least distance toward the ink side (white in dark
// phases) until it reads at 4.5:1 on the paper, the raised surface and the chip colour.
// Set FLOOR = false to emit the raw blog colours (amber #E6A23C, lush) instead.
const FLOOR = true;
const legible = (c, toward, ...grounds) => (FLOOR ? floored(c, toward, ...grounds) : c);
function floored(c, toward, ...grounds) { for (let t = 0; t <= 1; t += 0.01) { const m = mix(c, toward, t); if (grounds.every((g) => contrast(m, g) >= 4.5)) return m; } return toward; }

// Chips, tags and segmented tracks are borderless, so --surface-2 must stand apart from --surface (it sits on cards)
// in the same direction in every phase: lighter than the surface in dark phases, darker in light phases.
// Phase 17 (night palette, D7): the dark phases' own inputs. The fill, the text plum, the chart and track colours, and
// night's surfaces, are chosen to meet the targets in src/styles/sky.contrast.test.ts; text colours still pass the floor.
// Dawn's and dusk's tracks sit darker than their cards (inset): on those lighter grounds that is the only way a track
// stands apart from both the page and the card.
const DARK = {
  night: { surface: '#17233C', surface2: '#26344F', t2: '#B8C3C9', lush: '#8DC49A', accent: '#A9567E', accentText: '#EBB3CC', chartOut: '#7A8899', track: '#2A3550' },
  dawn: { accent: '#A9567E', accentText: '#EBB3CC', chartOut: '#919EAD', track: '#222C44' },
  dusk: { accent: '#A9567E', accentText: '#EBB3CC', chartOut: '#8A98A8', track: '#1E2434' },
};
// Ruling R3: a text input's, select's or textarea's edge is its only boundary, so it reads at 3:1 on the paper and the card.
function edgeFor(surface, ink, ...grounds) {
  for (let t = 0; t <= 1; t += 0.01) { const m = mix(surface, ink, t); if (grounds.every((g) => contrast(m, g) >= 3)) return m; }
  return ink;
}
export const GAP = 1.15; // minimum contrast ratio between --surface-2 and --surface
const chipFor = (dk, surface, bg) => {
  const ink = dk ? [255, 255, 255] : [30, 60, 90];
  const base = dk ? surface : bg; // dark: the chip on the raised surface; light: on the paper (darker than white cards)
  for (let a = dk ? 0.07 : 0.06; a <= 1; a += 0.005) {
    const c = over(ink, a, base);
    if (contrast(c, surface) >= GAP && (dk ? lum(c) > lum(surface) : lum(c) < lum(surface))) return c;
  }
  throw new Error('no chip colour separates from the surface');
};

export function tokens(name) {
  const p = P[name], dk = p.mode === 1, d = DARK[name];
  const bg = name === 'day' ? '#FAF8F3' : dk ? mix(p.sky[0], p.sky[1], 0.35) : mix(p.sky[2], '#FFFFFF', 0.55);
  const surface = d?.surface ?? (dk ? mix(p.sky[1], p.sky[0], 0.3) : '#FFFFFF');
  const surface2 = d?.surface2 ?? chipFor(dk, surface, bg);
  const toward = dk ? '#FFFFFF' : p.t1;
  const grounds = [bg, surface, surface2]; // every text colour must read at 4.5:1 on all three
  const inkMuted = legible(d?.t2 ?? p.t2, toward, ...grounds);
  const accent = dk ? d.accent : legible(p.fig, toward, ...grounds);
  const accentText = dk ? legible(d.accentText, toward, ...grounds) : accent;
  return {
    '--bg': bg,
    '--surface': surface,
    '--surface-2': surface2,
    '--ink': legible(p.t1, toward, ...grounds),
    '--ink-muted': inkMuted,
    '--line': rgba(p.t1, dk ? 0.24 : 0.14),
    '--line-strong': edgeFor(surface, p.t1, bg, surface),
    '--accent': accent,
    '--accent-ink': '#FFFFFF',
    '--accent-text': accentText,
    '--money-in': legible(d?.lush ?? p.lush, toward, ...grounds),
    '--warn': legible(dk ? mix('#E6A23C', '#FFFFFF', 0.25) : '#E6A23C', toward, ...grounds),
    '--danger': legible(dk ? '#D9797A' : '#9B3B3B', toward, ...grounds),
    '--focus': accentText,
    '--chart-out': dk ? d.chartOut : inkMuted,
    '--track': dk ? d.track : surface2,
    'color-scheme': dk ? 'dark' : 'light',
  };
}

// Build-time checks: fail rather than emit a palette where chips vanish on cards, text falls under 4.5:1, or a fill's
// label does. The full set of targets is the contrast test's.
for (const name of Object.keys(P)) {
  const t = tokens(name), dk = P[name].mode === 1;
  const gap = contrast(t['--surface-2'], t['--surface']);
  const lighter = lum(t['--surface-2']) > lum(t['--surface']);
  if (gap < GAP || lighter !== dk) throw new Error(`${name}: --surface-2 ${t['--surface-2']} too close to --surface ${t['--surface']} (${gap.toFixed(2)})`);
  for (const k of ['--ink', '--ink-muted', '--accent-text', ...(FLOOR ? ['--money-in', '--warn', '--danger'] : [])])
    for (const g of ['--bg', '--surface', '--surface-2'])
      if (contrast(t[k], t[g]) < 4.5) throw new Error(`${name}: ${k} ${t[k]} on ${g} ${t[g]} is ${contrast(t[k], t[g]).toFixed(2)}:1`);
  if (contrast(t['--accent-ink'], t['--accent']) < 4.5) throw new Error(`${name}: --accent-ink on --accent ${t['--accent']} is ${contrast(t['--accent-ink'], t['--accent']).toFixed(2)}:1`);
  for (const g of ['--bg', '--surface'])
    if (contrast(t['--line-strong'], t[g]) < 3) throw new Error(`${name}: --line-strong ${t['--line-strong']} on ${g} is ${contrast(t['--line-strong'], t[g]).toFixed(2)}:1`);
}

const block = (sel, name) => `${sel} {\n${Object.entries(tokens(name)).map(([k, v]) => `  ${k}: ${v};`).join('\n')}\n}\n`;
let css = `/* Generated by scripts/make-sky.mjs from the sky clock's clock.js (commit 0276c26). Do not edit by hand.
   The phase on <html data-phase> is the source of truth; lib/theme.ts sets it (Follow the sky, Light = day, Dark = night).
   :root carries the day palette as the default for a page with no data-phase.
   .theme-light / .theme-dark scope the day and night palettes inside a page (the /design page). */\n`;
for (const name of ORDER) {
  const sel = name === 'day' ? ':root, :root[data-phase="day"], .theme-light' : name === 'night' ? ':root[data-phase="night"], .theme-dark' : `:root[data-phase="${name}"]`;
  css += block(sel, name);
}
const out = new URL('../src/styles/sky.css', import.meta.url);
if (process.argv.includes('--check')) {
  if (readFileSync(out, 'utf8') !== css) { console.error('sky.css is out of date: run node scripts/make-sky.mjs'); process.exit(1); }
  console.log('sky.css matches scripts/make-sky.mjs');
} else {
  writeFileSync(out, css);
  console.log(`wrote ${out.pathname}: ${ORDER.length} phases; day --bg ${tokens('day')['--bg']}, night --bg ${tokens('night')['--bg']}`);
}
