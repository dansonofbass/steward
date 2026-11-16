// Claim T6 (docs/CLAIMS.md): no cheers on bad news. Money news gets no line, face or sound from the moment policy; the
// over-target line stays calm and borrows no cheer line; Review's sort cheer is quiet in a red month and on a fee (THO-7);
// and a scan of every source checks that a screen showing an over, overdue or shortfall state draws no cheer, and that
// every pool line sits behind momentAllowed.
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { createElement } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { redMonth, type HomeData } from '../api/home';
import { HOME, homeWith } from '../screens/home/fixtures';
import Review from '../screens/Review';
import { OCT } from '../screens/spending/fixtures';
import { inList, stubFetch, wrapBook } from '../test-utils';
import { POOLS, type Pool } from './lines';
import { momentAllowed, type Allowed, type MomentKind } from './momentAllowed';
import { overLine } from './spendingLine';

vi.mock('../celebrate/celebrate', () => ({ sorted: () => () => {}, quiet: () => () => {}, pop: () => {}, sunrise: () => {}, acorn: () => () => {} }));
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

const SOURCES: Record<string, string> = Object.fromEntries(
  Object.entries(import.meta.glob<string>('/src/**/*.{ts,tsx}', { query: '?raw', import: 'default', eager: true }))
    .filter(([path]) => !/\.test\.[jt]sx?$/.test(path)),
);

const NONE: Allowed = { face: false, motion: false, line: false, sound: false, golden: false };

// Word boundaries, so rollover_cents (a good-news screen's field) isn't read as over_cents.
const BAD_NEWS = /\b(over_cents|over_level|overdue|shortfall)\b/;
const CHEER = /\b(nextLine|drawFrom|payerCheer|sortCheer|importDoneLine|withCelebrate|useWinMoment|useAcornMotion)\s*\(/g;
const GENTLE = /\bnextLine\s*\(\s*(['"`])gentle\1/g;
const NEXT_LINE = /\bnextLine\s*\(\s*([^,)]*)/g;

/** The sources that name a bad-news state, and each cheer call in them ("path: name("). Snooze's gentle pool is fine. */
function cheersOnBadNews(sources: Record<string, string>): { badNews: string[]; hits: string[] } {
  const badNews = Object.keys(sources).filter((p) => BAD_NEWS.test(sources[p]));
  const hits = badNews.flatMap((p) => [...sources[p].replace(GENTLE, '').matchAll(CHEER)].map((m) => `${p}: ${m[1]}(`));
  return { badNews, hits };
}

/** The sources that draw from a pool other than gentle, and those of them that never call momentAllowed. */
function ungatedCheers(sources: Record<string, string>): { drawers: string[]; hits: string[] } {
  const drawers = Object.keys(sources).filter((p) => p !== '/src/lib/lines.ts'
    && [...sources[p].matchAll(NEXT_LINE)].some((m) => !/^(['"`])gentle\1$/.test(m[1].trim())));
  return { drawers, hits: drawers.filter((p) => !/\bmomentAllowed\s*\(/.test(sources[p])) };
}

const FEE = { id: 1, account_id: 1, account_name: 'Checking', posted_at: '2026-10-10', amount_cents: -3500, raw_description: 'OVERDRAFT FEE',
  merchant: null, category: 'uncategorized', is_business: false, is_transfer: false, business_pct: 0, business_line: null, business_source: 'none',
  category_source: 'none', reviewed_at: null, from_bank: true, note_count: 0, matching: 0 };
const QUEUE = { uncategorized: [FEE, { ...FEE, id: 2 }], count: 2, duplicates: [], duplicate_count: 0, top_categories: ['fees', 'transport'], business: [], business_count: 0, empty: false };
const RED = homeWith({ flow: { ...HOME.flow, in_cents: 100_000, out_cents: 140_000, net_cents: -40_000 } });

/** Sorts the overdraft fee in Review as `label` (Fees or Getting around), in a household book whose month is `home`, on
 *  a golden roll (a cheer on the first sort when one is allowed); the toast's cheer, or null. */
async function sortCheer(home: HomeData, category: 'fees' | 'transport', label: string): Promise<HTMLElement | null> {
  vi.spyOn(Math, 'random').mockReturnValue(0.01);
  stubFetch({ ...inList(), '/api/home': home, '/api/review': QUEUE,
    'PATCH /api/transactions/1': { ...FEE, category, result: { category, applied: 0, ids: [], rule: 'made', undo: 't1' } } });
  const { qc } = wrapBook(createElement(Review));
  await waitFor(() => expect(qc.getQueryData(['home', 'red'])).toBe(redMonth(home)));   // Review knows the month
  const card = (await screen.findAllByTestId('review-card')).find((c) => c.dataset.id === '1')!;
  fireEvent.click(within(card).getByRole('button', { name: label }));
  await waitFor(() => expect(document.querySelector('.undo-toast')).not.toBeNull());
  return screen.queryByTestId('toast-cheer');
}

/** A pool line as a pattern: its {placeholders} match any text. */
const linePattern = (line: string) =>
  new RegExp(line.split(/\{\w+\}/).map((s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('.+'));

describe('no cheers on bad news (T6)', () => {
  it('money news, Watching, Look into and Care never get a line, a face or a sound, in a red month or not', () => {
    for (const kind of ['money', 'watching', 'flags', 'care'] as MomentKind[]) {
      for (const parent of [false, true]) {
        for (const red of [undefined, false, true]) {
          expect(momentAllowed(kind, { parent, red }), `${kind} parent=${parent} red=${red}`).toEqual(NONE);
        }
      }
    }
  });

  it('a sort draws nothing in a red month or on a fee, and is still a win otherwise', () => {
    expect(momentAllowed('sort', { parent: false, red: true })).toEqual(NONE);
    for (const red of [undefined, false, true]) expect(momentAllowed('sort', { parent: false, red, fee: true }), `red=${red}`).toEqual(NONE);
    expect(momentAllowed('sort', { parent: false, red: false, fee: false })).toEqual({ face: true, motion: true, line: true, sound: true, golden: true });
  });

  it("Review's sort cheer plays in a month that isn't red", async () => {
    const cheer = await sortCheer(HOME, 'transport', 'Getting around');
    expect(cheer).not.toBeNull();
    expect(POOLS.goldenSort).toContain(cheer!.textContent);
  });

  it("Review's sort cheer is quiet in a red month", async () => {
    expect(await sortCheer(RED, 'transport', 'Getting around')).toBeNull();
  });

  it("Review's sort cheer is quiet on a fee", async () => {
    expect(await sortCheer(HOME, 'fees', 'Fees')).toBeNull();
  });

  it('the over-target line is calm and says none of the cheer lines', () => {
    const cheers = (Object.keys(POOLS) as Pool[]).filter((p) => p !== 'gentle').flatMap((p) => POOLS[p].map((l) => [p, l] as const));
    expect(cheers.length).toBeGreaterThan(50);
    const month = (level: 'clear' | 'little' | null) => ({
      ...OCT, current: true, day: 20,
      everyday: OCT.everyday.map((r) => {
        if (r.target_cents === null) return r;
        if (level && r.category === 'dining') return { ...r, spent_cents: r.target_cents + 14_000, over_cents: 14_000, over_level: level };
        return { ...r, spent_cents: Math.min(r.spent_cents, r.target_cents), over_cents: 0, over_level: 'on' as const };
      }),
    });
    for (const [level, tone] of [['clear', 'amber'], ['little', 'muted'], [null, 'quiet']] as const) {
      const line = overLine(month(level));
      expect(line, String(level)).not.toBeNull();
      expect(line!.tone).toBe(tone);
      const text = line!.bits.map((b) => b.text).join('');
      if (level) expect(text).toContain('Eating out');
      for (const [pool, l] of cheers) expect(text, `${pool}: ${l}`).not.toMatch(linePattern(l));
    }
  });

  it('no screen that shows an over, overdue or shortfall state draws a cheer', () => {
    const { badNews, hits } = cheersOnBadNews(SOURCES);
    expect(badNews.length).toBeGreaterThanOrEqual(3);
    expect(badNews).toContain('/src/lib/spendingLine.ts');
    expect(hits).toEqual([]);
  });

  it('every cheer drawn from a pool sits behind momentAllowed', () => {
    const { drawers, hits } = ungatedCheers(SOURCES);
    expect(drawers.length).toBeGreaterThanOrEqual(5);
    expect(hits).toEqual([]);
  });

  it('the scan sees a cheer drawn on an overdue screen', () => {
    const { badNews, hits } = cheersOnBadNews({
      '/src/screens/Bills.tsx': "if (bill.overdue) toast(nextLine('sort'));",
      '/src/screens/Snooze.tsx': "if (bill.overdue) toast(nextLine('gentle'));",
      '/src/screens/Maxed.tsx': "if (r.rollover_cents > 0) void withCelebrate((c) => c.burst({ over: el }));",
      '/src/screens/Late.tsx': "const n = rows.filter((r) => r.overdue).length; useWinMoment(host, 'coins', true);",
    });
    expect(badNews).toEqual(['/src/screens/Bills.tsx', '/src/screens/Snooze.tsx', '/src/screens/Late.tsx']);
    expect(hits).toEqual(['/src/screens/Bills.tsx: nextLine(', '/src/screens/Late.tsx: useWinMoment(']);
  });

  it('the gate check sees a pool line drawn without momentAllowed', () => {
    const { hits } = ungatedCheers({
      '/src/screens/Loose.tsx': "const line = nextLine('payday');",
      '/src/screens/Gated.tsx': "const a = momentAllowed('payday', ctx); const line = a.line ? nextLine('payday') : null;",
      '/src/screens/Snooze.tsx': "const line = nextLine('gentle');",
    });
    expect(hits).toEqual(['/src/screens/Loose.tsx']);
  });
});
