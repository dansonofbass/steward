// Issue #28: type is sized in rem, so the phone's text size setting reaches it. index.html opts in with the
// text-scale meta, which hands the root font size to the browser, so no stylesheet may set one. A size in px is
// left only on SVG chart text, which is drawn in its chart's own units and scales with the chart.
import { readdirSync, readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

const src = (rel: string) => new URL(rel, import.meta.url);
const read = (rel: string) => readFileSync(src(rel), 'utf8');
const CSS = readdirSync(src('../'), { recursive: true, encoding: 'utf8' }).map((f) => f.replace(/\\/g, '/')).filter((f) => f.endsWith('.css'));
const rules = (css: string) => [...css.replace(/\/\*[\s\S]*?\*\//g, '').matchAll(/([^{}]+)\{([^{}]*)\}/g)].map((m) => ({ selector: m[1].trim(), body: m[2] }));
// SVG text: a chart's <text>, the band chart's end labels and the sleeping acorn's z.
const SVG_TEXT = /(^|\s)text$|\.end-label$|\.acorn__z$/;

describe('type in rem (issue #28)', () => {
  it('reads every stylesheet', () => { expect(CSS.length).toBeGreaterThan(40); });

  it('sizes the six type tokens in rem, at the sizes they were in px', () => {
    const tokens = read('./tokens.css');
    const px = { 1: 13, 2: 15, 3: 17, 4: 22, 5: 28, 6: 40 };
    for (const [n, size] of Object.entries(px)) {
      const m = new RegExp(`--fs-${n}:\\s*([\\d.]+)rem;`).exec(tokens);
      expect(m, `--fs-${n}`).not.toBeNull();
      expect(Number(m![1]) * 16).toBe(size);
    }
  });

  it('opts in to the phone\'s text size, and no stylesheet sets the root font size', () => {
    expect(readFileSync(src('../../index.html'), 'utf8')).toMatch(/<meta name="text-scale" content="scale"\s*\/?>/);
    const found: string[] = [];
    for (const f of CSS) {
      for (const r of rules(read(`../${f}`))) {
        const root = r.selector.split(',').some((s) => /^(html|:root)(\[[^\]]*\])*$/.test(s.trim()));
        if (root && /(^|;)\s*font(-size)?\s*:/.test(r.body)) found.push(`${f}: ${r.selector}`);
      }
    }
    expect(found).toEqual([]);
  });

  it('keeps display figures at 40 px at the default text size on every phone, and caps them at the width when larger', () => {
    const token = /--fs-figure:\s*([^;]+);/.exec(read('./tokens.css'))![1];
    const size = (rootPx: number, widthPx: number) => {
      let e = token.replace(/var\(--fs-6\)/g, String(2.5 * rootPx)).replace(/([\d.]+)vw/g, (_, n: string) => String((Number(n) / 100) * widthPx))
        .replace(/([\d.]+)px/g, '$1');
      // Work out the innermost min() or max() until one number is left.
      for (let inner = /(min|max)\(([\d.,\s]+)\)/; inner.test(e);) {
        e = e.replace(inner, (_, f: string, list: string) => String(Math[f as 'min' | 'max'](...list.split(',').map(Number))));
      }
      expect(e, `--fs-figure: ${token}`).toMatch(/^[\d.]+$/);
      return Number(Number(e).toFixed(1));
    };
    expect([320, 360, 390, 1280].map((w) => size(16, w))).toEqual([40, 40, 40, 40]);
    expect(size(32, 390)).toBe(42.9);   // twice the text size: as wide as the phone allows
    expect(size(32, 320)).toBe(40);
  });

  // Before #28 the root was 15 px, so a rem meant 15 px; now it is the browser's 16. Each rem written then was scaled
  // by 15/16 so it keeps its size at the default text size. The px each rule's rems come to, in order (some lines also
  // carry a rem written at 16 px, like the tags' 20 px line height).
  it('keeps the rems from before #28 at the px they were (1 rem was 15 px then)', () => {
    const WAS: [string, string, number[]][] = [
      ['screens/Settings.css', '.line__lead', [210]], ['screens/Settings.css', '.line > .line__main', [180]],
      ['screens/accounts/invest/invest.css', '.inv-costform .field, .inv-feeform .field', [150]],
      ['screens/accounts/invest/invest.css', '.inv-costform', [142.5]],
      ['screens/business/business.css', '.biz-sum dt', [13.125]], ['screens/business/business.css', '.biz-range', [20.625]],
      ['screens/business/business.css', '.biz-year-switch .biz-years', [180]], ['screens/business/business.css', '.biz-point h3', [15]],
      ['screens/care/care.css', '.care-card__title', [15.75]], ['screens/care/care.css', '.care-headline', [20.25]],
      ['screens/care/care.css', '.care-years table', [13.5]],
      ['screens/chat/chat.css', '.chat-set-row > .stack', [180]], ['screens/chat/chat.css', '.chat__budget input', [150]],
      ['screens/home.css', '.group__head h3', [11.25]],
      ['screens/import/import.css', '.imp-row__line', [240]], ['screens/import/import.css', '.imp-confirm__table select', [180]],
      ['screens/import/import.css', '.imp-st__review tr', [165, 135]],
      ['screens/import/import.css', '.imp-st__held tr:not(.imp-st__rm)', [82.5, 97.5, 120]],
      ['screens/inventory/inventory.css', '.attn__main', [210]], ['screens/inventory/inventory.css', '.ifacts', [112.5]],
      ['screens/inventory/inventory.css', '.hist__when', [82.5]],
      ['screens/plan/plan.css', '.lever .tag--changed', [10.5, 18]], ['screens/plan/plan.css', '.nd__rate .field', [180]],
      ['screens/ready/ready.css', '.ready__form', [420]], ['screens/reimburse/reimburse.css', '.rb-inline input, .rb-inline select', [180]],
      ['screens/review.css', '.review .tag', [10.5, 20]], ['screens/transactions.css', '.tag', [10.5, 20]],
      ['screens/review/focus/focus.css', '.fcard .chip kbd', [10.8]], ['screens/review/focus/focus.css', '.focus__keys kbd', [10.8]],
      ['screens/watching/watching.css', '.frow', [165, 120]], ['screens/watching/watching.css', '.floor-in', [127.5]],
      ['screens/watching/watching.css', '.who', [82.5]], ['screens/watching/watching.css', '.large-in', [180]],
      ['styles/base.css', '.eyebrow', [11.25]], ['ui/SubNav.css', '.subnav', [37.5]], ['ui/UndoToast.css', '.stamp', [10.8]],
    ];
    const found: string[] = [];
    for (const [file, selector, px] of WAS) {
      const matches = rules(read(`../${file}`)).filter((r) => r.selector === selector && /rem\b/.test(r.body));
      const got = matches.flatMap((r) => [...r.body.matchAll(/([\d.]+)rem\b/g)].map((m) => Number(m[1]) * 16));
      if (JSON.stringify(got) !== JSON.stringify(px)) found.push(`${file} ${selector}: ${got.join(', ')} px, was ${px.join(', ')} px`);
    }
    expect(found).toEqual([]);
  });

  it('sizes no text in px, except SVG chart text', () => {
    const found: string[] = [];
    for (const f of CSS) {
      for (const r of rules(read(`../${f}`))) {
        if (!/font-size:\s*[\d.]+px|(^|[;\s])font:[^;]*\d+(\.\d+)?px/.test(r.body)) continue;
        if (r.selector.split(',').every((s) => SVG_TEXT.test(s.trim()))) continue;
        found.push(`${f}: ${r.selector}`);
      }
    }
    expect(found).toEqual([]);
  });
});
