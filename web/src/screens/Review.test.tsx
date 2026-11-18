import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { inList, reply, stubFetch, wrapBook } from '../test-utils';
import { LiveRegions } from '../ui/Live';
import Review from './Review';

afterEach(() => vi.unstubAllGlobals());
beforeEach(() => { localStorage.clear(); localStorage.setItem('steward-celebrations', 'off'); vi.spyOn(Math, 'random').mockReturnValue(0.5); });   // no golden, a cheer gap of 4
const TXN = { id: 7, account_id: 1, account_name: 'Checking', posted_at: '2026-10-10', amount_cents: -1200, raw_description: 'SQ *VENDOR', merchant: null, category: 'uncategorized', is_business: false, is_transfer: false, business_pct: 0, business_line: null, business_source: 'none', category_source: 'none', reviewed_at: null, from_bank: true, note_count: 0 };
const BIZ = { ...TXN, id: 8, raw_description: 'OFFICE DEPOT' };
const REVIEW = { uncategorized: [TXN], count: 40, duplicates: [], duplicate_count: 2, top_categories: ['groceries'], business: [BIZ], business_count: 3 };

describe('Review (roadmap 12: clearer counts, All caught up)', () => {
  it('titles the page Review and counts what is waiting by kind', async () => {
    stubFetch({ ...inList(), '/api/review': REVIEW });
    wrapBook(<Review />);
    expect(await screen.findByRole('heading', { level: 1, name: 'Review' })).toBeInTheDocument();
    const counts = screen.getByTestId('review-counts');
    expect(within(counts).getAllByText(/./).map((s) => s.textContent))
      .toEqual(['3 business or personal', '2 possible duplicates']);
    expect(screen.getByTestId('review-top')).toHaveTextContent('40 left');
    expect(screen.getByRole('heading', { level: 2, name: 'No category yet' })).toBeInTheDocument();
    // The page says once what Snooze does; the card's button points there.
    expect(screen.getByRole('button', { name: 'Snooze' })).toHaveAccessibleDescription(/Snooze brings one back in a week/);
  });

  it('says All caught up when nothing is waiting', async () => {
    stubFetch({ ...inList(), '/api/review': { ...REVIEW, uncategorized: [], count: 0, duplicate_count: 0, business: [], business_count: 0 } });
    wrapBook(<LiveRegions><Review /></LiveRegions>);
    // Said through the page's polite region (issue #23); the note itself is not a live region added with its words.
    await waitFor(() => expect(screen.getByTestId('live-said')).toHaveTextContent('All caught up.'));
    const note = screen.getByText('All caught up.').closest('.review__done');
    expect(note).not.toHaveAttribute('role');
    expect(screen.queryByTestId('review-counts')).toBeNull();
  });

  it('says Nothing here yet on a book with no transactions at all, not All caught up (phase 17, 2.7)', async () => {
    stubFetch({ ...inList(), '/api/review': { ...REVIEW, uncategorized: [], count: 0, duplicate_count: 0, business: [], business_count: 0, empty: true } });
    wrapBook(<LiveRegions><Review /></LiveRegions>);
    await waitFor(() => expect(screen.getByTestId('live-said')).toHaveTextContent('Nothing here yet. Import a file and Steward starts sorting.'));
    expect(screen.queryByText('All caught up.')).toBeNull();
  });

  it('is not All caught up while possible duplicates wait (final review 3)', async () => {
    stubFetch({ ...inList(), '/api/review': { ...REVIEW, uncategorized: [], count: 0, business: [], business_count: 0, duplicate_count: 2 } });
    wrapBook(<Review />);
    expect(await screen.findByTestId('review-counts')).toHaveTextContent('2 possible duplicates');
    expect(screen.queryByText('All caught up.')).toBeNull();
  });

  it('More opens every category grouped, and picking one sorts the transaction', async () => {
    const fetchMock = stubFetch({ ...inList(), '/api/review': REVIEW, 'PATCH /api/transactions/7': { ...TXN, category: 'gifts' } });
    wrapBook(<Review />);
    fireEvent.click(await screen.findByRole('button', { name: 'More…' }));
    const sheet = screen.getByRole('dialog', { name: 'Category' });
    fireEvent.click(within(sheet).getByRole('option', { name: 'Gifts' }));
    expect(screen.queryByRole('dialog')).toBeNull();
    await waitFor(() => expect(fetchMock.mock.calls.some(([u, i]) => String(u).endsWith('/transactions/7') && (i as RequestInit)?.method === 'PATCH')).toBe(true));
  });
});

describe('Review (phase 12: reasons, guesses, the spread offer, counts and progress)', () => {
  const UNSURE = { ...TXN, id: 9, raw_description: 'UNION SERVICE CENTER', reason: 'unsure', guess: 'home' };
  const ZELLE = { ...TXN, id: 10, raw_description: 'ZELLE TO SAM', merchant: 'Zelle', reason: 'p2p', guess: null };
  const Q = { ...REVIEW, uncategorized: [UNSURE, ZELLE, { ...TXN, reason: 'waiting', guess: null }], count: 3, business: [], business_count: 0, duplicate_count: 0,
    sorted_count: 312, background: { pending: 420, done: 230, waiting: false } };

  it('says why each row is here and shows the guess as the first, highlighted chip', async () => {
    stubFetch({ ...inList(), '/api/review': Q });
    wrapBook(<Review />);
    const card = (await screen.findAllByTestId('review-card')).find((c) => c.dataset.id === '9')!;
    expect(within(card).getByText("Steward wasn't sure enough to sort it.")).toBeInTheDocument();
    const chips = within(card).getAllByRole('button').filter((b) => b.classList.contains('chip')).map((b) => b.textContent);
    expect(chips).toEqual(['Home and garden', 'Groceries', 'More…']);
    expect(within(card).getByRole('button', { name: 'Home and garden' })).toHaveClass('chip--guess');
    const zelle = screen.getAllByTestId('review-card').find((c) => c.dataset.id === '10')!;
    expect(within(zelle).getByText("A Zelle payment: the description doesn't say what it was for.")).toBeInTheDocument();
    expect(within(screen.getAllByTestId('review-card').find((c) => c.dataset.id === '7')!).getByText('Waiting for Steward to look.')).toBeInTheDocument();
  });

  it('with no categorizer coming, a row says no rule matches it, and no gateway line shows (INS-21)', async () => {
    stubFetch({ ...inList(), '/api/review': { ...Q, uncategorized: [{ ...TXN, reason: 'no_rule', guess: null }], count: 1,
      background: { pending: 1, done: 0, waiting: true, expected: false } } });
    wrapBook(<Review />);
    const card = (await screen.findAllByTestId('review-card'))[0];
    expect(within(card).getByText('No rule matches it yet.')).toBeInTheDocument();
    expect(screen.queryByText(/Waiting for/)).toBeNull();
  });

  it('counts the rows Steward sorted, with a link, and shows the background progress', async () => {
    stubFetch({ ...inList(), '/api/review': Q });
    wrapBook(<Review />);
    const link = await screen.findByRole('link', { name: '312 sorted by Steward, not checked yet' });
    expect(link).toHaveAttribute('href', '/b/ours/transactions?sorted=steward&dates=all');
    expect(screen.getByTestId('review-background')).toHaveTextContent('Categorizing in the background: 230 of 650');
  });

  it('says it is waiting for the gateway, and nothing when nothing is pending', async () => {
    stubFetch({ ...inList(), '/api/review': { ...Q, background: { pending: 650, done: 0, waiting: true } } });
    const { unmount } = wrapBook(<Review />);
    expect(await screen.findByTestId('review-background')).toHaveTextContent('Waiting for the gateway to categorize 650');
    unmount();
    stubFetch({ ...inList(), '/api/review': { ...Q, background: { pending: 0, done: 0, waiting: true } } });
    wrapBook(<Review />);
    await screen.findByRole('heading', { level: 1, name: 'Review' });
    expect(screen.queryByTestId('review-background')).toBeNull();
  });
});

describe('Review cards: asked up front (sorting redesign, reworded by review focus P7)', () => {
  const C = { ...TXN, reason: 'unknown', guess: null };
  it('the box for the rows like it, ticked; a line when nothing matches; nothing when no rule can be made', async () => {
    stubFetch({ ...inList(), '/api/review': { ...REVIEW, business: [], business_count: 0, duplicate_count: 0, count: 4,
      uncategorized: [{ ...C, id: 9, matching: 6 }, { ...C, id: 12, matching: 1 }, { ...C, id: 7, matching: 0 }, { ...C, id: 11, raw_description: '*ABC', matching: null }] } });
    wrapBook(<Review />);
    const cardOf = (id: number) => screen.getAllByTestId('review-card').find((c) => c.dataset.id === String(id))!;
    await screen.findAllByTestId('review-card');
    expect(within(cardOf(9)).getByRole('checkbox', { name: 'Also the 6 like it' })).toBeChecked();
    expect(within(cardOf(12)).getByRole('checkbox', { name: 'Also the one like it' })).toBeChecked();
    expect(within(cardOf(7)).getByText('Nothing else like it yet. Steward will remember your choice.')).toBeInTheDocument();
    expect(within(cardOf(11)).queryByRole('checkbox')).toBeNull();
    expect(within(cardOf(11)).queryByText(/Steward will remember/)).toBeNull();
  });

  it('a failed sort keeps the card and its chips, and says nothing changed', async () => {
    stubFetch({ ...inList(), '/api/review': { ...REVIEW, uncategorized: [C], count: 1 }, 'PATCH /api/transactions/7': () => reply({ error: 'Nope.' }, 500) });
    wrapBook(<Review />);
    fireEvent.click(within(await screen.findByTestId('review-card')).getByRole('button', { name: 'Groceries' }));
    await waitFor(() => expect(screen.getByTestId('review-card')).toHaveTextContent('Not saved. Nope. Nothing changed.'));
    expect(screen.queryByTestId('slim-row')).toBeNull();
    expect(screen.getByRole('button', { name: 'Groceries' })).toBeEnabled();
  });
});

describe('Review from the first run (guided setup spec 2.4)', () => {
  const row = (id: number) => ({ ...TXN, id, raw_description: `SHOP ${id}` });
  const sortedAs = (r: { id: number }) => ({ ...r, category: 'transport', result: { category: 'transport', applied: 0, ids: [], rule: 'made', undo: `t${r.id}` } });
  const queue = (rows: { id: number }[]) => ({ uncategorized: rows, count: rows.length, duplicates: [], duplicate_count: 0, top_categories: ['transport'], business: [], business_count: 0, empty: false });
  const routes = (rows: { id: number }[]) => Object.fromEntries(rows.map((r) => [`PATCH /api/transactions/${r.id}`, sortedAs(r)]));
  async function sort(id: number) {
    const c = (await screen.findAllByTestId('review-card')).find((x) => x.dataset.id === String(id))!;
    fireEvent.click(within(c).getByRole('button', { name: 'Getting around' }));
    await waitFor(() => expect(screen.getAllByTestId('slim-row').some((s) => s.dataset.id === String(id))).toBe(true));
  }

  it('shows Back to setup from welcome after five sorts or when nothing is left', async () => {
    const rows = [1, 2, 3, 4, 5, 6, 7].map(row);
    stubFetch({ ...inList(), '/api/review': queue(rows), ...routes(rows) });
    wrapBook(<Review />, {}, '/b/ours/review?from=welcome');
    for (const id of [1, 2, 3, 4]) await sort(id);
    expect(screen.queryByRole('link', { name: 'Back to setup' })).toBeNull();
    await sort(5);
    expect(await screen.findByRole('link', { name: 'Back to setup' })).toHaveAttribute('href', '/b/ours/welcome?step=extras');
  });

  it('shows it at once when the queue is empty, and never without from=welcome', async () => {
    stubFetch({ ...inList(), '/api/review': queue([]) });
    const first = wrapBook(<Review />, {}, '/b/ours/review?from=welcome');
    expect(await screen.findByRole('link', { name: 'Back to setup' })).toBeInTheDocument();
    first.unmount();
    wrapBook(<Review />, {}, '/b/ours/review');
    expect(await screen.findByText('All caught up.')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Back to setup' })).toBeNull();
  });
});
