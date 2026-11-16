import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { POOLS } from '../lib/lines';
import { HOME } from './home/fixtures';
import { inList, stubFetch, wrapBook } from '../test-utils';
import Review from './Review';

const fx = vi.hoisted(() => ({
  sorted: vi.fn(() => () => {}), quiet: vi.fn(() => () => {}), pop: vi.fn(), sunrise: vi.fn(),
  acorn: vi.fn((_o: { svg: SVGSVGElement; motion: string; sound?: boolean }) => () => {}),
}));
vi.mock('../celebrate/celebrate', () => fx);

const TXN = { id: 1, account_id: 1, account_name: 'Checking', posted_at: '2026-10-10', amount_cents: -1200, raw_description: 'A SHOP', merchant: null,
  category: 'uncategorized', is_business: false, is_transfer: false, business_pct: 0, business_line: null, business_source: 'none',
  category_source: 'none', reviewed_at: null, from_bank: true, note_count: 0, matching: 0 };
const row = (id: number) => ({ ...TXN, id, raw_description: `SHOP ${id}` });
const queue = (rows: object[]) => ({ uncategorized: rows, count: rows.length, duplicates: [], duplicate_count: 0, top_categories: ['transport'], business: [], business_count: 0, empty: false });
const sortedAs = (r: { id: number }) => ({ ...r, category: 'transport', result: { category: 'transport', applied: 0, ids: [], rule: 'made', undo: `t${r.id}` } });
const routes = (rows: { id: number }[]) => Object.fromEntries(rows.map((r) => [`PATCH /api/transactions/${r.id}`, sortedAs(r)]));
async function sort(id: number) {
  const c = (await screen.findAllByTestId('review-card')).find((x) => x.dataset.id === String(id))!;
  fireEvent.click(within(c).getByRole('button', { name: 'Getting around' }));
  await waitFor(() => expect(screen.getAllByTestId('slim-row').some((s) => s.dataset.id === String(id))).toBe(true));
}

beforeEach(() => { for (const f of Object.values(fx)) f.mockClear(); });
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("Review's cheers (phase 17 spec 3.7)", () => {
  it('the toast cheers on the 4th sort when the gap rolls 4, with the win face, and not before', async () => {
    vi.spyOn(Math, 'random').mockReturnValue(0.5);              // never golden, a gap of 4
    const rows = [1, 2, 3, 4].map(row);
    stubFetch({ ...inList(), '/api/home': HOME, '/api/review': queue(rows), ...routes(rows) });
    wrapBook(<Review />);
    for (const id of [1, 2, 3]) {
      await sort(id);
      expect(screen.queryByTestId('toast-cheer')).toBeNull();
    }
    await sort(4);
    const cheer = await screen.findByTestId('toast-cheer');
    expect(POOLS.sort).toContain(cheer.textContent);
    expect(cheer.querySelector('svg.acorn')).toHaveAttribute('data-face', 'win');
    expect(within(cheer.closest('.undo-toast') as HTMLElement).getByRole('button', { name: 'Undo' })).toBeInTheDocument();   // the slim rows have their own Undo
  });

  it('a golden sort cheers at once, with the golden face and a golden line', async () => {
    vi.spyOn(Math, 'random').mockReturnValue(0.01);
    stubFetch({ ...inList(), '/api/home': HOME, '/api/review': queue([row(1), row(2)]), ...routes([row(1)]) });
    const { qc } = wrapBook(<Review />);
    await waitFor(() => expect(qc.getQueryData(['home', 'red'])).toBe(false));   // the month isn't red
    await sort(1);
    const cheer = await screen.findByTestId('toast-cheer');
    expect(POOLS.goldenSort).toContain(cheer.textContent);
    expect(cheer.querySelector('svg.acorn')).toHaveAttribute('data-face', 'golden');
    await waitFor(() => expect(fx.acorn).toHaveBeenCalledWith(expect.objectContaining({ motion: 'golden' })));
  });

  it("doesn't cheer while it can't tell whether the month is red (Home doesn't answer)", async () => {
    vi.spyOn(Math, 'random').mockReturnValue(0.01);
    stubFetch({ ...inList(), '/api/review': queue([row(1), row(2)]), ...routes([row(1)]) });
    wrapBook(<Review />);
    await sort(1);
    await waitFor(() => expect(document.querySelector('.undo-toast')).not.toBeNull());
    expect(screen.queryByTestId('toast-cheer')).toBeNull();
  });

  it('a parent book never cheers a sort and shows no face (spec 3.5)', async () => {
    vi.spyOn(Math, 'random').mockReturnValue(0.01);
    const rows = [1, 2, 3, 4, 5].map(row);
    stubFetch({ ...inList(), '/api/review': queue(rows), ...routes(rows) });
    wrapBook(<Review />, { kind: 'parent' });
    for (const id of [1, 2, 3, 4, 5]) await sort(id);
    expect(screen.queryByTestId('toast-cheer')).toBeNull();
    expect(document.querySelector('svg.acorn')).toBeNull();
  });
});

describe('All caught up (spec 3.7)', () => {
  it('the resting acorn dozes on its horizon with a caughtUp line', async () => {
    vi.spyOn(Math, 'random').mockReturnValue(0.5);
    stubFetch({ ...inList(), '/api/review': queue([]) });
    wrapBook(<Review />);
    const line = await screen.findByTestId('caught-up-line');
    expect(POOLS.caughtUp).toContain(line.textContent);
    expect(document.querySelector('.review__horizon svg.acorn')).toHaveAttribute('data-face', 'resting');
    await waitFor(() => expect(fx.acorn).toHaveBeenCalledWith(expect.objectContaining({ motion: 'doze', sound: false })));
  });

  it('can be golden: the golden face and a golden line', async () => {
    vi.spyOn(Math, 'random').mockReturnValue(0.01);
    stubFetch({ ...inList(), '/api/review': queue([]) });
    wrapBook(<Review />);
    expect(POOLS.goldenSort).toContain((await screen.findByTestId('caught-up-line')).textContent);
    expect(document.querySelector('.review__horizon svg.acorn')).toHaveAttribute('data-face', 'golden');
  });

  it('under reduced motion the still acorn and its words stay and are announced, and no motion is asked for', async () => {
    vi.stubGlobal('matchMedia', (q: string) => ({ matches: q.includes('reduce'), media: q, addEventListener: () => {}, removeEventListener: () => {} }));
    stubFetch({ ...inList(), '/api/review': queue([]) });
    wrapBook(<Review />);
    const status = (await screen.findByTestId('caught-up-line')).closest('[role="status"]')!;   // PR 1's always-mounted status is the other one
    expect(status.querySelector('svg.acorn')).not.toBeNull();
    await Promise.resolve();
    expect(fx.acorn).not.toHaveBeenCalled();
  });

  it('a parent book: the warm line, with no acorn', async () => {
    stubFetch({ ...inList(), '/api/review': queue([]) });
    wrapBook(<Review />, { kind: 'parent' });
    expect(POOLS.caughtUp).toContain((await screen.findByTestId('caught-up-line')).textContent);
    expect(document.querySelector('svg.acorn')).toBeNull();
  });

  it("an empty book (the review answer's empty, ruling R4): PR 1's line, with no acorn, no caughtUp line and no motion", async () => {
    vi.spyOn(Math, 'random').mockReturnValue(0.01);                  // even a golden roll changes nothing
    stubFetch({ ...inList(), '/api/review': { ...queue([]), empty: true } });
    wrapBook(<Review />);
    expect(await screen.findByText('Nothing here yet. Import a file and Steward starts sorting.')).toBeInTheDocument();
    expect(document.querySelector('svg.acorn')).toBeNull();
    expect(screen.queryByTestId('caught-up-line')).toBeNull();
    await Promise.resolve();
    expect(fx.acorn).not.toHaveBeenCalled();
  });
});
