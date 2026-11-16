import { describe, expect, it } from 'vitest';
import { CATEGORY_ORDER } from '../lib/categories';
import { MOMENT_DELAY_MS, MOMENT_MS, MOMENT_NAMES, MOMENTS, momentFor } from './moments';

describe('category moments (sorting redesign, Category moments)', () => {
  it('gives the twelve their own moment (Income, Interest and Reimbursement share the coins) and every other category the sparkle', () => {
    expect(Object.keys(MOMENT_NAMES).sort()).toEqual(['dining', 'entertainment', 'gifts', 'groceries', 'health', 'home',
      'income', 'interest', 'pets', 'reimbursement', 'transfer', 'transport', 'travel', 'utilities']);
    expect(new Set(Object.values(MOMENT_NAMES)).size).toBe(12);
    for (const k of CATEGORY_ORDER) expect(momentFor(k)).toBe(MOMENTS[MOMENT_NAMES[k] ?? 'sparkle']);
    expect(momentFor('fees')).toBe(MOMENTS.sparkle);
  });

  it('are small inline SVGs: no image file, no link, no emoji, and every moving part is there', () => {
    for (const [name, m] of Object.entries(MOMENTS)) {
      expect(m.svg, name).toMatch(/^<svg viewBox="0 0 64 64"/);
      expect(m.svg, name).not.toMatch(/<image|href|url\(|<script/i);
      expect(m.svg, name).not.toMatch(/\p{Extended_Pictographic}/u);
      expect(m.svg.length, name).toBeLessThan(800);
      for (const mv of m.moves) expect(m.svg, name).toContain(`class="${mv.part}"`);
    }
  });

  it('move only transform and opacity, and end within 1.6 s', () => {
    for (const m of Object.values(MOMENTS)) {
      for (const mv of m.moves) for (const f of mv.frames) for (const k of Object.keys(f)) expect(['transform', 'opacity', 'offset', 'easing']).toContain(k);
    }
    expect(MOMENT_DELAY_MS + MOMENT_MS).toBeLessThanOrEqual(1600);
  });

  it('Profile adds the mortarboard toss and the house with a lit window, transform and opacity only', () => {
    for (const name of ['mortarboard', 'house']) {
      const m = MOMENTS[name];
      expect(m.svg.startsWith('<svg')).toBe(true);
      for (const mv of m.moves) {
        expect(m.svg).toContain(`class="${mv.part}"`);
        for (const f of mv.frames) for (const k of Object.keys(f)) expect(['transform', 'opacity', 'offset', 'easing']).toContain(k);
      }
    }
  });
});
