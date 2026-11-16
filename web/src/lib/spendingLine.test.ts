import { describe, expect, it } from 'vitest';
import type { OverLevel, SpendingMonth } from '../api/types';
import { OCT, SEP } from '../screens/spending/fixtures';
import { overLine } from './spendingLine';

/** OCT with these categories over by these cents at these levels, and every other targeted one on target. */
const over = (rows: Record<string, [number, OverLevel]>, m: SpendingMonth = OCT): SpendingMonth => ({
  ...m, everyday: m.everyday.map((r) => {
    if (r.target_cents === null) return r;
    const o = rows[r.category];
    return o ? { ...r, spent_cents: r.target_cents + o[0], state: 'over' as const, over_cents: o[0], over_level: o[1] }
      : { ...r, spent_cents: Math.min(r.spent_cents, r.target_cents), state: 'on_track' as const, over_cents: 0, over_level: 'on' as const };
  }),
});
const text = (m: SpendingMonth) => overLine(m)!.bits.map((b) => b.text).join('');
const links = (m: SpendingMonth) => overLine(m)!.bits.filter((b) => b.to).map((b) => [b.text, b.to]);

describe('the over-target line (decision 2)', () => {
  it("says everything is within its targets when nothing is over, quietly, with no links", () => {
    expect(overLine(over({}))).toEqual({ tone: 'quiet', bits: [{ text: "Everything's within its targets." }] });
  });
  it('one a little over: muted, its figures and See it', () => {
    const m = over({ dining: [1_200, 'little'] });
    expect(text(m)).toBe('Eating out is a little over its target · $512 of $500 · See Eating out');
    expect(overLine(m)!.tone).toBe('muted');
    expect(links(m)).toEqual([['See Eating out', '/spending/dining?month=2026-10']]);
  });
  it('one clearly over: amber, never red, by how much', () => {
    const m = over({ dining: [14_000, 'clear'] });
    expect(text(m)).toBe('Eating out is $140 over its target · See Eating out');
    expect(overLine(m)!.tone).toBe('amber');
  });
  it('two or three name each, largest first, each a link; amber only if one is clearly over (P16)', () => {
    const two = over({ dining: [14_000, 'clear'], shopping: [6_000, 'little'] });
    expect(text(two)).toBe('2 categories are over: Eating out $140 · Shopping $60');
    expect(overLine(two)!.tone).toBe('amber');
    expect(links(two)).toEqual([['Eating out', '/spending/dining?month=2026-10'], ['Shopping', '/spending/shopping?month=2026-10']]);
    const three = over({ dining: [1_200, 'little'], shopping: [2_000, 'little'], transport: [1_500, 'little'] });
    expect(text(three)).toBe('3 categories are over: Shopping $20 · Getting around $15 · Eating out $12');
    expect(overLine(three)!.tone).toBe('muted');
  });
  it("ties keep Spending's order", () => {
    expect(text(over({ shopping: [6_000, 'little'], dining: [6_000, 'little'] }))).toBe('2 categories are over: Eating out $60 · Shopping $60');
  });
  it('four or more sum it up and link to the whole section', () => {
    const five = over({ dining: [14_000, 'clear'], groceries: [9_000, 'little'], shopping: [6_000, 'clear'], home: [1_000, 'little'], transport: [10_000, 'clear'] });
    expect(text(five)).toBe('5 categories are over, $400 in all. Eating out is furthest, $140. See all 5');
    expect(links(five)).toEqual([['See all 5', '/spending?month=2026-10#flexible']]);
  });
  it('on days 1-7 only clearly over shows, from the month the server sent', () => {
    const early = { ...over({ dining: [1_200, 'little'] }), day: 7, days_left: 24 };
    expect(text(early)).toBe("Everything's within its targets.");
    expect(text({ ...early, day: 8 })).toBe('Eating out is a little over its target · $512 of $500 · See Eating out');
    expect(text({ ...over({ dining: [14_000, 'clear'] }), day: 3 })).toBe('Eating out is $140 over its target · See Eating out');
    expect(text({ ...over({ dining: [1_200, 'little'] }, SEP), day: null })).toContain('a little over');   // a closed month
  });
  it('has no line without a Flexible target (ruling 26), or without a month', () => {
    expect(overLine({ ...OCT, head: { ...OCT.head, everyday_target_cents: 0 } })).toBeNull();
    expect(overLine(undefined)).toBeNull();
  });
});

describe("overLine and Home's narrowed month (Home spec P26)", () => {
  it('reads the Flexible sign\'s over rows without a whole SpendingMonth', () => {
    expect(overLine({
      month: '2026-10', current: true, day: 30, head: { everyday_target_cents: 50_000 },
      everyday: [{ category: 'dining', spent_cents: 64_000, target_cents: 50_000, over_cents: 14_000, over_level: 'clear' }],
    })).toEqual({ tone: 'amber', bits: [{ text: 'Eating out is $140 over its target' }, { text: ' · ' }, { text: 'See Eating out', to: '/spending/dining?month=2026-10' }] });
  });
});
