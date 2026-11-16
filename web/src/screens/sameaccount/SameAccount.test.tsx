import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import * as celebrate from '../../celebrate/celebrate';
import { callsTo, renderAt, reply, stubFetch } from '../../test-utils';
import { HELD, HELD_TEXT, MERGE_REPLY, MERGED_TEXT, PAIR, PAIR_TEXT } from './fixtures';
import SameAccount from './SameAccount';

beforeEach(() => { localStorage.clear(); localStorage.setItem('steward-celebrations', 'off'); });
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });
const show = (role: 'manager' | 'viewer' = 'manager') => renderAt(<SameAccount />, { role }, '/');
const para = (s: string) => (_: string, el: Element | null) => el?.tagName === 'P' && el.textContent === s;
const motion = (reduce: boolean) => vi.stubGlobal('matchMedia', (q: string) => ({
  matches: reduce && q === '(prefers-reduced-motion: reduce)', media: q, addEventListener: () => {}, removeEventListener: () => {} }));

async function mergeOnce() {
  let asked = [HELD];
  const fetchMock = stubFetch({
    '/api/same-accounts': () => reply({ questions: asked }),
    'POST /api/same-accounts/held-7/merge': () => { asked = []; return reply(MERGE_REPLY); },
    'POST /api/undo/tok': () => { asked = [HELD]; return reply({ undone: 5, transaction: null }); },
  });
  show();
  fireEvent.click(await screen.findByRole('button', { name: 'Merge them' }));
  expect(await screen.findByText(para(MERGED_TEXT))).toBeInTheDocument();
  return fetchMock;
}

describe('the Same account? card (same-account spec, Asking)', () => {
  it('asks about each open question, newest first, with both answers', async () => {
    stubFetch({ '/api/same-accounts': { questions: [HELD, PAIR] } });
    show();
    expect(await screen.findByText(para(HELD_TEXT))).toBeInTheDocument();
    expect(screen.getByText(para(PAIR_TEXT))).toBeInTheDocument();
    const cards = screen.getAllByRole('region', { name: 'Same account?' });
    expect(cards).toHaveLength(2);
    expect(within(cards[0]).getByText(para(HELD_TEXT))).toBeInTheDocument();
    for (const card of cards) {
      expect(within(card).getByRole('button', { name: 'Merge them' })).toBeInTheDocument();
      expect(within(card).getByRole('button', { name: "They're different" })).toBeInTheDocument();
    }
  });

  it('shows nothing when there is nothing to ask, or when the list cannot load', async () => {
    const fetchMock = stubFetch({ '/api/same-accounts': { questions: [] } });
    const first = show();
    await waitFor(() => expect(callsTo(fetchMock, 'GET', '/api/same-accounts')).toHaveLength(1));
    expect(first.container).toBeEmptyDOMElement();
    first.unmount();
    const failing = stubFetch({});
    const second = show();
    await waitFor(() => expect(callsTo(failing, 'GET', '/api/same-accounts')).toHaveLength(1));
    expect(second.container).toBeEmptyDOMElement();
  });

  it('after Merge them the card says what happened and cheers, and Undo brings the question back', async () => {
    const fetchMock = await mergeOnce();
    expect(screen.getByText('One account, as it should be.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Merge them' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Undo' }));
    expect(await screen.findByText('Undone.')).toBeInTheDocument();
    expect(await screen.findByRole('button', { name: 'Merge them' })).toBeInTheDocument();
    expect(callsTo(fetchMock, 'POST', '/api/undo/tok')).toHaveLength(1);
  });

  it('with reduced motion the cheer still shows and the burst never starts', async () => {
    localStorage.removeItem('steward-celebrations');
    motion(true);
    const closer = vi.spyOn(celebrate, 'closer');
    await mergeOnce();
    expect(screen.getByText('One account, as it should be.')).toBeInTheDocument();
    await new Promise((r) => { setTimeout(r, 50); });
    expect(closer).not.toHaveBeenCalled();
  });

  it('without reduced motion, and with Celebrations on, a merge starts the quiet burst', async () => {
    localStorage.removeItem('steward-celebrations');
    motion(false);
    const closer = vi.spyOn(celebrate, 'closer');
    await mergeOnce();
    await waitFor(() => expect(closer).toHaveBeenCalledTimes(1));
  });

  it("after They're different the card says Kept apart. with Undo", async () => {
    let asked = [PAIR];
    stubFetch({
      '/api/same-accounts': () => reply({ questions: asked }),
      'POST /api/same-accounts/pair-2/different': () => { asked = []; return reply({ undo: 'tok2' }); },
    });
    show();
    fireEvent.click(await screen.findByRole('button', { name: "They're different" }));
    expect(await screen.findByText('Kept apart.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Undo' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Same account?' })).toBeInTheDocument();
  });

  it('says why an answer failed and keeps the question', async () => {
    stubFetch({
      '/api/same-accounts': { questions: [HELD] },
      'POST /api/same-accounts/held-7/merge': () => reply({ error: 'That question was already answered.' }, 404),
    });
    show();
    fireEvent.click(await screen.findByRole('button', { name: 'Merge them' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('That question was already answered.');
    expect(screen.getByRole('button', { name: 'Merge them' })).toBeInTheDocument();
  });

  it('a viewer reads the question without the buttons', async () => {
    stubFetch({ '/api/same-accounts': { questions: [HELD] } });
    show('viewer');
    expect(await screen.findByText(para(HELD_TEXT))).toBeInTheDocument();
    expect(screen.queryByRole('button')).toBeNull();
    expect(screen.getByText('A manager of this book can answer this.')).toBeInTheDocument();
  });
});
