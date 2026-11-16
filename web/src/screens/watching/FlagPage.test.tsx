import { fireEvent, screen, within } from '@testing-library/react';
import { Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { BookSummary } from '../../api/types';
import { askState, resetAsk } from '../../ask/store';
import { callsTo, reply, stubFetch, wrapBook } from '../../test-utils';
import type { FlagPage as Page } from './api';
import { FlagPage } from './FlagPage';
import { DENTIST_PAGE, GIFT_PAGE, PARENT, PREMIUM_PAGE } from './fixtures';

afterEach(() => vi.unstubAllGlobals());
const open = (id: number, book: Partial<BookSummary> = PARENT) =>
  wrapBook(<Routes><Route path="/b/:slug/look-into/:id" element={<FlagPage />} /></Routes>, book, `/b/margaret-ellis/look-into/${id}`);

/** GET answers whatever the last write left, as the server would. */
function server(start: Page, writes: Record<string, (body: Record<string, unknown>) => Page | Response>) {
  let state = start;
  return stubFetch({
    [`/api/flags/${start.id}`]: () => reply(state),
    ...Object.fromEntries(Object.entries(writes).map(([action, fn]) => [`POST /api/flags/${start.id}/${action}`, (_u: string, init: RequestInit) => {
      const out = fn(JSON.parse(String(init.body ?? '{}')));
      if (out instanceof Response) return out;
      state = out;
      return reply(out);
    }])),
  });
}

describe('A flag page', () => {
  it('reads like the gift card mockup', async () => {
    server(GIFT_PAGE, {});
    open(41);
    expect(await screen.findByRole('heading', { name: '$500.00 gift card at CVS Pharmacy' })).toBeInTheDocument();
    const why = screen.getByRole('region', { name: 'Why it was flagged' });
    expect(within(why).getByText('Scam pattern:')).toBeInTheDocument();
    expect(within(why).getByText(GIFT_PAGE.why)).toBeInTheDocument();
    expect(within(why).getByText('($500.00 or more)')).toBeInTheDocument();
    const txn = screen.getByRole('region', { name: 'The transaction' });
    expect(within(txn).getByText('Sat, Oct 17, 2026')).toBeInTheDocument();
    expect(within(txn).getByText('(Margaret and Robert (husband))')).toBeInTheDocument();
    expect(within(txn).getByText('CVS/PHARMACY #09812 GIFT CARD FULLERTON CA')).toBeInTheDocument();
    const earlier = screen.getByRole('region', { name: 'Earlier at CVS Pharmacy' });
    expect(within(earlier).getByText(GIFT_PAGE.earlier!.line)).toBeInTheDocument();
    expect(within(earlier).getAllByText('CVS Pharmacy')).toHaveLength(3);
    expect(screen.getByRole('link', { name: /Joint checking/ })).toHaveAttribute('href', '/b/margaret-ellis/inventory/1');
    expect(screen.getByText('Urgent email sent to JR and Robin')).toBeInTheDocument();
    const actions = screen.getByRole('region', { name: 'What did you find?' });
    expect(within(actions).getAllByRole('button').map((b) => b.textContent)).toEqual(['Expected', 'Handled', 'Still checking']);
  });
  it('marks a large amount Expected for about this amount, then undoes it', async () => {
    const expected: Page = { ...DENTIST_PAGE, status: 'expected', status_label: 'Expected', done: true, expected: null,
      known: { id: 4, label: 'Brea Family Dental, $480 to $800' },
      done_line: 'Marked Expected. Brea Family Dental, $480 to $800, added to Known payees.' };
    const fetchMock = server(DENTIST_PAGE, { expected: () => expected, reopen: () => ({ ...DENTIST_PAGE, done_line: 'Reopened.' }) });
    open(33);
    fireEvent.click(within(await screen.findByRole('region', { name: 'What did you find?' })).getByRole('button', { name: 'Expected' }));
    const sheet = await screen.findByRole('dialog', { name: 'Mark Expected' });
    expect(within(sheet).getByRole('radio', { name: /Not for about this amount/ })).toBeChecked();
    expect(within(sheet).getByText('Brea Family Dental, $480 to $800. A bigger payment is still flagged.')).toBeInTheDocument();
    fireEvent.change(within(sheet).getByLabelText('Note (optional)'), { target: { value: "Margaret's crown." } });
    fireEvent.click(within(sheet).getByRole('button', { name: 'Mark Expected' }));
    expect(await screen.findByText('Marked Expected. Brea Family Dental, $480 to $800, added to Known payees.')).toBeInTheDocument();
    expect(callsTo(fetchMock, 'POST', '/api/flags/33/expected')[0].body).toEqual({ scope: 'about', note: "Margaret's crown." });
    fireEvent.click(screen.getByRole('button', { name: 'Undo' }));
    await vi.waitFor(() => expect(callsTo(fetchMock, 'POST', '/api/flags/33/reopen')).toHaveLength(1));
  });
  it('Handled needs a note, and the sheet shows the server says so', async () => {
    server(GIFT_PAGE, { handled: () => reply({ error: 'Add a note saying what was done.' }, 422) });
    open(41);
    fireEvent.click(within(await screen.findByRole('region', { name: 'What did you find?' })).getByRole('button', { name: 'Handled' }));
    const sheet = await screen.findByRole('dialog', { name: 'Mark Handled' });
    expect(within(sheet).getByText("Required. Everyone in the book can read it, and it's kept in the change record.")).toBeInTheDocument();
    fireEvent.click(within(sheet).getByRole('button', { name: 'Mark Handled' }));
    expect(await within(sheet).findByText('Add a note saying what was done.')).toBeInTheDocument();
  });
  it('after Still checking the note sits at the top with Change the note', async () => {
    const checking: Page = { ...GIFT_PAGE, status: 'checking', status_label: 'Still checking', by: 'JR, Oct 18',
      note: 'Calling Margaret this morning to ask about it.', note_by: 'JR', status_at: '2026-10-18T15:02:00+00:00', done_line: null };
    server(GIFT_PAGE, { checking: () => checking });
    open(41);
    fireEvent.click(within(await screen.findByRole('region', { name: 'What did you find?' })).getByRole('button', { name: 'Still checking' }));
    const sheet = await screen.findByRole('dialog', { name: 'Mark Still checking' });
    fireEvent.change(within(sheet).getByLabelText('Note (optional)'), { target: { value: checking.note } });
    fireEvent.click(within(sheet).getByRole('button', { name: 'Mark Still checking' }));
    expect(await screen.findByText('JR is checking:')).toBeInTheDocument();
    expect(screen.getByText('"Calling Margaret this morning to ask about it."')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Change the note' })).toBeInTheDocument();
  });
  it('a viewer sees everything and no action buttons', async () => {
    server({ ...GIFT_PAGE, can_edit: false, viewer_line: 'Only managers can mark flags. Emails for this book are set in Settings → Watching.' }, {});
    open(41, { ...PARENT, role: 'viewer' });
    expect(await screen.findByText('Only managers can mark flags. Emails for this book are set in Settings → Watching.')).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'What did you find?' })).toBeNull();
    expect(screen.getByText('Flagged by the checks after the bank feed sync')).toBeInTheDocument();
  });
  it('a removed transaction is said so', async () => {
    server({ ...GIFT_PAGE, transaction: { ...GIFT_PAGE.transaction!, removed: true, id: null, joint_names: null, category_label: null } }, {});
    open(41);
    expect(await screen.findByText('This transaction was removed from the book after it was flagged. What it said is kept here.')).toBeInTheDocument();
  });
  it('a missed premium leads with its recent payments and the policy', async () => {
    server(PREMIUM_PAGE, {});
    open(39);
    expect(await screen.findByRole('heading', { name: "Long-term care premium hasn't left" })).toBeInTheDocument();
    expect(screen.getByText(PREMIUM_PAGE.fact)).toBeInTheDocument();
    expect(screen.getAllByText('EVERGREEN MUTUAL LTC PREM')).toHaveLength(2);
    expect(screen.getByText('Policy ••7730 · Evergreen Mutual: (800) 555-0142')).toBeInTheDocument();
    expect(screen.getByText(PREMIUM_PAGE.expected_note!)).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'The transaction' })).toBeNull();
  });
  it('the missed premium Expected sheet says to edit the item, not that the flag closes itself', async () => {
    server(PREMIUM_PAGE, {});
    open(39);
    fireEvent.click(within(await screen.findByRole('region', { name: 'What did you find?' })).getByRole('button', { name: 'Expected' }));
    const sheet = await screen.findByRole('dialog', { name: 'Mark Expected' });
    expect(within(sheet).getByText(/edit the item so the check looks for the right payment/)).toBeInTheDocument();
    expect(within(sheet).queryByText(/closes when/i)).toBeNull();
  });
});

describe('Ask about this on a flag (Surfaces)', () => {
  afterEach(() => { resetAsk(); });
  it('asks about the flag by its id: its check and day go, never its words', async () => {
    server(GIFT_PAGE, {});
    open(GIFT_PAGE.id, { ...PARENT, chat: true });
    fireEvent.click(await screen.findByRole('button', { name: `Ask about ${GIFT_PAGE.check_label} flag` }));
    expect(askState().about).toStrictEqual({ kind: 'flag', id: GIFT_PAGE.id });
    expect(askState().surface).toStrictEqual({ kind: 'flag' });
  });
});
