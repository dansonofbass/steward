import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useFakeTimers } from '../test-clock';
import { inList, stubFetch, wrapBook } from '../test-utils';
import Review from './Review';

const loaded = vi.hoisted(() => vi.fn());
vi.mock('../celebrate/celebrate', () => {
  loaded();
  return { sorted: vi.fn(), quiet: vi.fn(), pop: vi.fn(), sunrise: vi.fn(), acorn: vi.fn(() => () => {}), winMoment: vi.fn(() => () => {}) };
});

const TXN = { id: 9, account_id: 1, account_name: 'Checking', posted_at: '2026-10-10', amount_cents: -1200, raw_description: 'UNION SERVICE CENTER',
  merchant: null, category: 'uncategorized', is_business: false, is_transfer: false, business_pct: 0, business_line: null, business_source: 'none',
  category_source: 'none', reviewed_at: null, from_bank: true, note_count: 0, matching: 0 };
const Q = { uncategorized: [TXN], count: 1, duplicates: [], duplicate_count: 0, top_categories: ['transport'], business: [], business_count: 0 };
const SORTED = { ...TXN, category: 'transport', result: { category: 'transport', applied: 0, rule: 'made', undo: 't' } };

beforeEach(() => { useFakeTimers(); localStorage.clear(); vi.spyOn(Math, 'random').mockReturnValue(0.5); });   // no golden, a cheer gap of 4
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

async function sortAndWait() {
  stubFetch({ ...inList(), '/api/review': Q, 'PATCH /api/transactions/9': SORTED });
  wrapBook(<Review />);
  fireEvent.click(within((await screen.findAllByTestId('review-card'))[0]).getByText('Getting around', { selector: 'button' }));
  expect(await screen.findByTestId('slim-row')).toHaveTextContent('SORTED · UNION SERVICE CENTER as Getting around · Undo');
  await waitFor(() => expect(document.querySelector('.undo-toast')).toHaveTextContent('SORTED · UNION SERVICE CENTER → Getting around'));
}

describe('with celebrations off, nothing of them loads (sorting redesign, decision 9 and Performance 3)', () => {
  it('switched off in Appearance: the slim row and the toast still show, no chunk loads', async () => {
    localStorage.setItem('steward-celebrations', 'off');
    await sortAndWait();
    expect(loaded).not.toHaveBeenCalled();
  });

  it('on a device set to reduce motion: no chunk either', async () => {
    vi.stubGlobal('matchMedia', (q: string) => ({ matches: q.includes('reduce'), media: q, addEventListener: () => {}, removeEventListener: () => {} }));
    await sortAndWait();
    expect(loaded).not.toHaveBeenCalled();
  });
});

describe('with motion off, Ten in a row and the milestones stay as words (phase 17, 2.7)', () => {
  it('the live region is mounted and empty before anything is said, so a screen reader hears the words', async () => {
    localStorage.setItem('steward-celebrations', 'off');
    stubFetch({ ...inList(), '/api/review': Q });
    wrapBook(<Review />);
    await screen.findAllByTestId('review-card');
    const region = screen.getByTestId('review-said');
    expect(region).toHaveAttribute('role', 'status');
    expect(region).toBeEmptyDOMElement();
  });

  it('switched off: the milestone shows under the top bar and is announced, and no chunk loads', async () => {
    localStorage.setItem('steward-celebrations', 'off');
    localStorage.setItem('steward-sorts', JSON.stringify({ total: 99 }));
    await sortAndWait();
    const said = await screen.findByText("That's 100 sorted on this device!");
    expect(said).toHaveClass('review__said');
    expect(said).toHaveAttribute('role', 'status');
    expect(said).toHaveAttribute('aria-live', 'polite');
    expect(loaded).not.toHaveBeenCalled();
  });

  it('on a device set to reduce motion: the same words', async () => {
    vi.stubGlobal('matchMedia', (q: string) => ({ matches: q.includes('reduce'), media: q, addEventListener: () => {}, removeEventListener: () => {} }));
    localStorage.setItem('steward-sorts', JSON.stringify({ total: 99 }));
    await sortAndWait();
    expect(await screen.findByText("That's 100 sorted on this device!")).toHaveAttribute('role', 'status');
    expect(loaded).not.toHaveBeenCalled();
  });
});
