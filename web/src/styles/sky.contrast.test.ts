// Phase 17 (spec 2.1 and 2.8): the contrast targets, checked over the palettes scripts/make-sky.mjs GENERATES into
// sky.css, in every phase, so a later colour change can't quietly break dark. Change the generator's inputs, never sky.css.
import { describe, expect, it } from 'vitest';
import { PALETTES } from '../celebrate/season';
import { REVIEW_EMPTY_BOOK } from '../lib/copy';
import { DARK_PHASES, PHASES, type Phase } from '../lib/sky';
import { contrast, luminance, over } from '../test-colour';
import { allCss, readCss, rules } from '../test-css';

type Palette = Record<string, string>;
const PALETTE = new Map<Phase, Palette>();
for (const r of rules(readCss('styles/sky.css'))) {
  const phase = r.sel.map((s) => /data-phase="(\w+)"/.exec(s)?.[1]).find(Boolean) as Phase | undefined;
  if (!phase) continue;
  const decls = r.body.split(';').map((d) => d.split(':').map((x) => x.trim())).filter((d) => d.length === 2 && d[0]);
  PALETTE.set(phase, Object.fromEntries(decls));
}
const tok = (p: Phase, k: string): string => {
  const v = PALETTE.get(p)?.[k];
  if (!v) throw new Error(`${p} has no ${k}`);
  return v;
};
const DARK = PHASES.filter((p) => DARK_PHASES.has(p));
const LIGHT = PHASES.filter((p) => !DARK_PHASES.has(p));
const GROUNDS = ['--bg', '--surface', '--surface-2'];
const TEXT = ['--ink', '--ink-muted', '--accent-text', '--money-in', '--warn', '--danger'];
// Ruling R2: dawn and dusk keep white text on the plum fill, and that text must read at 4.5:1 on it (pinned below). Their
// grounds are too light for the same fill to also reach 3:1 against them, and it needn't: WCAG 1.4.11 asks for no
// boundary on a control identified by its own visible text label, and every plum-filled button, chip and selected segment
// carries one (a tick's state is its white mark, also 4.5:1 on the fill). The fill still stands 2.2:1 from the page there.
const FILL_EXEMPT: readonly Phase[] = ['dawn', 'dusk'];
// The light phases gain exactly these tokens. Three equal today's equivalents (the value is the token they copy);
// --line-strong is new on purpose (ruling R3: form fields get a 3:1 edge). Every other light token is pinned below.
const LIGHT_NEW: Record<string, string | null> = { '--accent-text': '--accent', '--chart-out': '--ink-muted', '--track': '--surface-2', '--line-strong': null };
const lum = (c: string) => luminance(over(c, '#000000'));
function atLeast(min: number, p: Phase, fg: string, bg: string) {
  const r = contrast(tok(p, fg), tok(p, bg));
  expect(r, `${p}: ${fg} ${tok(p, fg)} on ${bg} ${tok(p, bg)} is ${r.toFixed(2)}:1`).toBeGreaterThanOrEqual(min);
}

// The light phases as they were before phase 17 (main 5f04e18): nothing in them may move.
const LIGHT_TODAY: Record<string, Palette> = {
  sunrise: { '--bg': '#FBEDDF', '--surface': '#FFFFFF', '--surface-2': '#EEE2D7', '--ink': '#1E2226', '--ink-muted': '#3B4148',
    '--line': 'rgba(30, 34, 38, 0.14)', '--accent': '#7A3550', '--accent-ink': '#FFFFFF', '--money-in': '#437040', '--warn': '#7E5F31',
    '--danger': '#9B3B3B', '--focus': '#7A3550', 'color-scheme': 'light' },
  morning: { '--bg': '#F9F7F3', '--surface': '#FFFFFF', '--surface-2': '#ECECEA', '--ink': '#18222B', '--ink-muted': '#3F4D59',
    '--line': 'rgba(24, 34, 43, 0.14)', '--accent': '#7C3352', '--accent-ink': '#FFFFFF', '--money-in': '#38783C', '--warn': '#836534',
    '--danger': '#9B3B3B', '--focus': '#7C3352', 'color-scheme': 'light' },
  day: { '--bg': '#FAF8F3', '--surface': '#FFFFFF', '--surface-2': '#EDEDEA', '--ink': '#17212A', '--ink-muted': '#42505C',
    '--line': 'rgba(23, 33, 42, 0.14)', '--accent': '#7C3352', '--accent-ink': '#FFFFFF', '--money-in': '#33793B', '--warn': '#856534',
    '--danger': '#9B3B3B', '--focus': '#7C3352', 'color-scheme': 'light' },
  afternoon: { '--bg': '#F8F2E6', '--surface': '#FFFFFF', '--surface-2': '#EBE7DE', '--ink': '#1F2124', '--ink-muted': '#3F3E3C',
    '--line': 'rgba(31, 33, 36, 0.14)', '--accent': '#80344F', '--accent-ink': '#FFFFFF', '--money-in': '#41733A', '--warn': '#826130',
    '--danger': '#9B3B3B', '--focus': '#80344F', 'color-scheme': 'light' },
  evening: { '--bg': '#F8E4CD', '--surface': '#FFFFFF', '--surface-2': '#EBDAC6', '--ink': '#1C1D21', '--ink-muted': '#37332F',
    '--line': 'rgba(28, 29, 33, 0.14)', '--accent': '#823A48', '--accent-ink': '#FFFFFF', '--money-in': '#4A6A33', '--warn': '#7B5C2E',
    '--danger': '#9B3B3B', '--focus': '#823A48', 'color-scheme': 'light' },
};

describe('the generated palettes (phase 17, spec 2.1)', () => {
  it('has a block for every phase, and its dark ones are lib/sky DARK_PHASES', () => {
    expect([...PALETTE.keys()].sort()).toEqual([...PHASES].sort());
    for (const p of PHASES) expect(tok(p, 'color-scheme'), p).toBe(DARK_PHASES.has(p) ? 'dark' : 'light');
  });

  it('text and links read at 4.5:1 on --bg, --surface and --surface-2', () => {
    for (const p of PHASES) for (const fg of TEXT) for (const bg of GROUNDS) atLeast(4.5, p, fg, bg);
  });

  it("a fill's label reads at 4.5:1 on it, and it is white in every phase (the drawn tick's mark is a white SVG)", () => {
    for (const p of PHASES) atLeast(4.5, p, '--accent-ink', '--accent');
    for (const p of PHASES) expect(tok(p, '--accent-ink'), p).toBe('#FFFFFF');
  });

  it('form fields have an edge of 3:1 on the page and on cards, in every phase (ruling R3)', () => {
    for (const p of PHASES) for (const bg of ['--bg', '--surface']) atLeast(3, p, '--line-strong', bg);
  });

  it('the focus ring is --accent-text, and it and the control rings reach 3:1 on every ground', () => {
    for (const p of PHASES) {
      expect(tok(p, '--focus'), p).toBe(tok(p, '--accent-text'));
      for (const bg of GROUNDS) { atLeast(3, p, '--focus', bg); atLeast(3, p, '--ink-muted', bg); }
    }
  });

  it('chart marks reach 3:1 on the page and on cards, and every fill that sits on a track reaches 3:1 on it', () => {
    for (const p of PHASES) {
      for (const fg of ['--chart-out', '--money-in']) for (const bg of ['--bg', '--surface']) atLeast(3, p, fg, bg);
      for (const fg of ['--accent-text', '--money-in', '--chart-out', '--warn', '--danger']) atLeast(3, p, fg, '--track');
    }
  });

  it('the plum fill reaches 3:1 on the page and on cards (dawn and dusk, ruling R2: 2.2:1 on the page), lighter than the page in the dark', () => {
    for (const p of PHASES) {
      if (FILL_EXEMPT.includes(p)) atLeast(2.2, p, '--accent', '--bg');
      else for (const bg of ['--bg', '--surface']) atLeast(3, p, '--accent', bg);
    }
    for (const p of DARK) expect(lum(tok(p, '--accent')), p).toBeGreaterThan(lum(tok(p, '--bg')));
  });

  it("tracks stand apart from cards (and from the page in the dark phases); the dark phases' borders reach 1.75:1", () => {
    for (const p of PHASES) atLeast(1.15, p, '--track', '--surface');
    for (const p of DARK) {
      atLeast(1.15, p, '--track', '--bg');
      atLeast(1.75, p, '--line', '--surface');
      atLeast(1.75, p, '--line', '--bg');
    }
  });

  it('the current tab is clearly brighter than the others in the dark phases; in light it is the plum', () => {
    for (const p of DARK) atLeast(1.25, p, '--ink', '--ink-muted');      // the dark tab is --ink (Nav.css)
    for (const p of LIGHT) expect(tok(p, '--accent-text'), p).not.toBe(tok(p, '--ink-muted'));
  });

  it('money out never outshines money in, in the dark phases', () => {
    for (const p of DARK) expect(lum(tok(p, '--chart-out')), p).toBeLessThan(lum(tok(p, '--money-in')));
  });

  it('light phases: the only new tokens are LIGHT_NEW (three copies and R3\'s --line-strong), and nothing else moved', () => {
    for (const p of LIGHT) {
      expect(Object.keys(PALETTE.get(p) ?? {}).sort(), p).toEqual([...Object.keys(LIGHT_TODAY[p]), ...Object.keys(LIGHT_NEW)].sort());
      for (const [k, copy] of Object.entries(LIGHT_NEW)) if (copy) expect(tok(p, k), `${p} ${k}`).toBe(tok(p, copy));
      for (const [k, v] of Object.entries(LIGHT_TODAY[p])) expect(tok(p, k), `${p} ${k}`).toBe(v);
    }
  });
});

describe('dark-only rules (phase 17)', () => {
  it('dark-only rules name all three dark phases and .theme-dark', () => {
    const wrong: string[] = [];
    for (const [file, css] of allCss()) {
      if (file === 'styles/sky.css') continue;
      for (const m of css.matchAll(/[^{}]*data-phase="night"[^{}]*\{/g)) {
        if (!['data-phase="dawn"', 'data-phase="dusk"', '.theme-dark'].every((s) => m[0].includes(s))) wrong.push(`${file}: ${m[0].trim()}`);
      }
    }
    expect(wrong).toEqual([]);
  });
});

// The deliberate light changes of phase 17, by name: the orchestrator's rulings and the spec. The light-token test above
// pins every light colour except --line-strong (R3), and the screenshot gate holds the light shots to the audit's before
// shots apart from these. Adding a light change means adding it here, with its ruling or spec section.
const has = (file: string, selector: string, decl: string) => () =>
  rules(readCss(file)).some((r) => r.sel.includes(selector) && r.body.includes(decl));
const LIGHT_LEDGER: readonly [name: string, inPlace: () => boolean][] = [
  ['R1: Steward draws every tick and radio, light included', has('styles/base.css', ':is(input[type="checkbox"]:not(.pick-box), input[type="radio"])', 'appearance: none')],
  ['R3: form fields have a 3:1 edge (--line-strong)', has('styles/base.css', 'select', 'border: 1px solid var(--line-strong)')],
  ['R4: the chosen Inventory pill is the plum fill with white text', has('screens/inventory/inventory.css', '.inv-seg label.is-on', 'color: var(--accent-ink); background: var(--accent)')],
  ['2.2: a fieldset card has no groove border', has('ui/Card.css', 'fieldset.card', 'border: 0')],
  ['2.5: the light snow reads on paper', () => PALETTES.snow.light.join() === '#5E7FA3,#4A6A8E,#54749A'],
  ['2.7: the Care legend keeps marker-sized svgs', has('screens/care/care.css', '.care-legend svg', 'flex: none')],
  ['2.7, then #22: a phone tab row scrolls with its edges faded instead of cutting a label', has('ui/SubNav.css', '.subnav.more-end', '--subnav-fade-end')],
  ['2.7: Appearance\'s switches sit beside their words', has('screens/Settings.css', '.line.check-row', 'justify-content: flex-start')],
  ['2.7: an empty book says so in Review', () => REVIEW_EMPTY_BOOK === 'Nothing here yet. Import a file and Steward starts sorting.'],
];

describe('the deliberate light changes (phase 17)', () => {
  it('each named change is in place', () => {
    expect(LIGHT_LEDGER.filter(([, inPlace]) => !inPlace()).map(([name]) => name)).toEqual([]);
  });
});
