import { beforeEach, describe, expect, it } from 'vitest';
import {
  cheerGap, drawFrom, fill, freshCheers, GOLDEN_ODDS, importDoneLine, MILESTONE_NAME, nextLine, payerCheer, POOLS, rollGolden,
  sortCheer, spareWeeks,
} from './lines';

beforeEach(() => localStorage.clear());
/** A small seeded generator, so a count over many rolls is the same every run. */
function seeded(seed: number): () => number {
  let s = seed >>> 0;
  return () => {
    s = (s + 0x6d2b79f5) >>> 0;
    let t = Math.imul(s ^ (s >>> 15), 1 | s);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
const sequence = (xs: number[]) => { let i = 0; return () => xs[i++ % xs.length]; };

describe('the line pools (phase 17 spec 3.2)', () => {
  it('keeps the 52 sort cheers as the first four pools', () => {
    expect([POOLS.sort.length, POOLS.big.length, POOLS.gentle.length, POOLS.reimbursement.length]).toEqual([30, 8, 6, 8]);
    expect(new Set([...POOLS.sort, ...POOLS.big, ...POOLS.gentle, ...POOLS.reimbursement]).size).toBe(52);
    expect(POOLS.sort).toContain('Sorted. Your future self says thanks.');
  });

  it("holds the new moments' lines verbatim", () => {
    expect(POOLS.caughtUp).toEqual(['Nothing to sort. The books are tidy.', 'All caught up. Go do something fun.',
      "Every one sorted. Steward's got the rest.", 'Clean slate.']);
    expect(POOLS.importDone).toEqual(['{rows} in. {waiting} in Review.', '{rows} in, and nothing to sort.']);
    expect(POOLS.payday).toEqual(['Payday came.', 'Payday came. Nicely done.']);
    expect(POOLS.setAsideCovered).toEqual(['{name} is covered, with {weeks} to spare.']);
    expect(POOLS.setAsideFirst).toEqual(["{month} won't sting this year."]);
    expect(POOLS.profileDone).toEqual(['All five. The plan has what it needs.']);
    expect(POOLS.gatewayBack).toEqual(['{gateway} is back. Catching up.']);
    expect(POOLS.goldenSort).toEqual(['A golden acorn. Rare find.', 'That one sparkled.', 'One in forty. Lucky you.']);
    expect(POOLS.planChecklistDone).toEqual(['Every box ticked. The plan can see you now.']);       // R2: no count, 6 or 7
    expect(MILESTONE_NAME.covered).toBe("the first set-aside covered before it's due");              // R1
  });

  it('never repeats until the bag is empty, then starts a new one, kept on this device', () => {
    const first = Array.from({ length: 30 }, () => nextLine('sort'));
    expect(new Set(first).size).toBe(30);
    expect(POOLS.sort).toContain(nextLine('sort'));
    expect(JSON.parse(localStorage.getItem('steward-cheers')!).sort).toHaveLength(29);
  });

  it('never says the same line twice in a row, even where one bag ends and the next begins', () => {
    // First shuffle keeps the order a, b, c; the second would start with c, the line just said.
    const r = sequence([0.9, 0.9, 0.1, 0.9]);
    const said = Array.from({ length: 4 }, () => drawFrom('t', ['a', 'b', 'c'], r));
    expect(said.slice(0, 3)).toEqual(['a', 'b', 'c']);
    expect(said[3]).not.toBe('c');
  });

  it('a broken bag starts afresh, and a blocked storage still draws', () => {
    localStorage.setItem('steward-cheers', '{not json');
    expect(POOLS.big).toContain(nextLine('big'));
  });

  it('fills a line from its values, and leaves an unknown one as it is', () => {
    expect(fill('{name} is covered, with {weeks} to spare.', { name: 'Property tax', weeks: '3 weeks' }))
      .toBe('Property tax is covered, with 3 weeks to spare.');
    expect(fill('{x} stays', {})).toBe('{x} stays');
    expect(payerCheer('Acme')).not.toContain('{');
  });

  it('an import says how many wait and why, or that nothing does, in the singular for one (R3, issue 32)', () => {
    expect(importDoneLine(143, 12)).toBe('143 rows in. 12 to sort in Review.');
    expect(importDoneLine(1, 1)).toBe('1 row in. 1 to sort in Review.');
    expect(importDoneLine(5, 1, 0)).toBe('5 rows in. 1 to sort in Review.');
    expect(importDoneLine(5, 0, 1)).toBe('5 rows in. 1 possible duplicate in Review.');
    expect(importDoneLine(5, 0, 2)).toBe('5 rows in. 2 possible duplicates in Review.');
    expect(importDoneLine(3, 1, 1)).toBe('3 rows in. 1 to sort and 1 possible duplicate in Review.');
    expect(importDoneLine(1_204, 1_100, 0)).toBe('1,204 rows in. 1,100 to sort in Review.');
    expect(importDoneLine(1_204, 0)).toBe('1,204 rows in, and nothing to sort.');
    expect(importDoneLine(1, 0, 0)).toBe('1 row in, and nothing to sort.');
  });

  it('says the time to spare in weeks, a week or days', () => {
    expect([spareWeeks(1), spareWeeks(5), spareWeeks(7), spareWeeks(13), spareWeeks(21), spareWeeks(30)])
      .toEqual(['a day', '5 days', 'a week', 'a week', '3 weeks', '4 weeks']);
  });
});

describe('rare surprises (spec 3.3)', () => {
  it('rolls golden about 1 in 40, from a random source the test gives', () => {
    expect(GOLDEN_ODDS).toBe(1 / 40);
    expect(rollGolden(() => 0.0249)).toBe(true);
    expect(rollGolden(() => 0.025)).toBe(false);
    const r = seeded(17);
    let n = 0;
    for (let i = 0; i < 40_000; i++) if (rollGolden(r)) n++;
    expect(n).toBeGreaterThan(900);
    expect(n).toBeLessThan(1_100);
  });

  it('cheers every 3rd to 5th sort', () => {
    expect([cheerGap(() => 0), cheerGap(() => 0.5), cheerGap(() => 0.999)]).toEqual([3, 4, 5]);
    const r = () => 0.5;                                    // never golden, and a gap of 4
    let s = freshCheers(r);
    const lines = Array.from({ length: 8 }, () => { const d = sortCheer(s, 0, true, r); s = d.next; return d.line; });
    expect(lines.map((l) => l !== null)).toEqual([false, false, false, true, false, false, false, true]);
    expect(POOLS.sort).toContain(lines[3]);
  });

  it('a sort that also set 3 or more matching rows cheers from the big pool', () => {
    const d = sortCheer({ since: 2, gap: 3 }, 3, false, () => 0.5);
    expect(POOLS.big).toContain(d.line);
  });

  it('a golden sort cheers at once with a golden line, and only where golden is allowed', () => {
    const golden = sortCheer({ since: 0, gap: 5 }, 0, true, () => 0.01);
    expect(golden.golden).toBe(true);
    expect(POOLS.goldenSort).toContain(golden.line);
    expect(sortCheer({ since: 0, gap: 5 }, 0, false, () => 0.01)).toMatchObject({ line: null, golden: false });
  });
});

describe('the guided setup pools (spec 9)', () => {
  it('say what the spec says', () => {
    expect(POOLS.setupStep).toEqual(['One down.', "That's in.", 'Nice. Next one.']);
    expect(POOLS.planted).toEqual(['It grows as your books do.']);
    expect(POOLS.ready).toEqual(['Nothing needs you.']);
  });
});
