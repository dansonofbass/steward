import { fireEvent, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { callsTo, reply, stubFetch, wrapBook } from '../../test-utils';
import type { ItemRow, Suggestion } from './api';
import { Suggestions } from './Suggestions';

afterEach(() => vi.unstubAllGlobals());
const PARENT = { slug: 'margaret-ellis', name: 'Margaret Ellis', kind: 'parent' as const, owners: [{ key: 'margaret', label: 'Margaret' }, { key: 'joint', label: 'Joint' }] };
const ANNUITY = { id: 6, kind: 'account', name: 'Deferred annuity', institution: 'Westmark Life', last4: '5521', status: 'needs_checking', sub: 'Westmark Life · annuity ••5521', type_word: 'annuity' } as ItemRow;
const PENSION = { id: 11, kind: 'income', name: 'County Schools pension', institution: 'County Schools Retirement', last4: null, status: 'confirmed', sub: 'Monthly, around the 1st · into ••4417', type_word: 'pension' } as ItemRow;
const S: Suggestion = {
  id: 1, kind: 'income', payer: 'Westmark Life', eyebrow: 'Suggested: income · annuity', title: 'Westmark Life pays Margaret $410.00 a month',
  why: '4 deposits into Wells Fargo ••4417 from the same payer, about a month apart.', forms: [], noun: 'deposits', count: 4, prefill: {}, filled_line: '', likely_ids: [6],
  phrase: 'an annuity deposit',
  evidence: [{ raw: 'WESTMARK LIFE ANN PMT 5521', amount_cents: 41000, posted_at: '2026-10-15', account: 'Wells Fargo ••4417' }],
};
const H: Suggestion = { ...S, id: 3, kind: 'account', payer: 'Harbor Savings Bank', eyebrow: 'Suggested: account · Needs checking', title: 'Interest from Harbor Savings Bank', likely_ids: [] };

describe("Is this one of Margaret's?", () => {
  it("links to an item with the confirm box, answers Not Margaret's, and undoes", async () => {
    const fetchMock = stubFetch({
      '/api/inventory/suggestions': { suggestions: [S, H] }, '/api/inventory': { items: [ANNUITY, PENSION], suggestions: null },
      'POST /api/inventory/suggestions/1/link': () => reply({ answer: { id: 1, icon: 'check', line: 'Linked to Deferred annuity, now Confirmed', sub: 'Westmark Life · 4 deposits' } }),
      'POST /api/inventory/suggestions/3/dismiss': () => reply({ answer: { id: 3, icon: 'x', line: "Not Margaret's: Harbor Savings Bank", sub: "Won't be suggested again. Change this under Settings → Dismissed suggestions." } }),
      'POST /api/inventory/suggestions/3/undo': () => reply({ ok: true }),
    });
    wrapBook(<Suggestions />, PARENT, '/b/margaret-ellis/inventory/suggestions');
    expect(await screen.findByText('Westmark Life pays Margaret $410.00 a month')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: "Is this one of Margaret's?" })).toBeInTheDocument();
    expect(screen.getByText(/2 to go through/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Add as income' })).toHaveAttribute('href', '/b/margaret-ellis/inventory/new?suggestion=1');
    const card = screen.getByRole('article', { name: 'Westmark Life pays Margaret $410.00 a month' });
    fireEvent.click(within(card).getByRole('button', { name: 'Already listed' }));
    const sheet = screen.getByRole('dialog', { name: 'Which item is it?' });
    expect(within(sheet).getByText('Likely, same institution')).toBeInTheDocument();
    expect(within(sheet).getByRole('radio', { name: /Deferred annuity/ })).toBeChecked();
    expect(within(sheet).getByRole('checkbox', { name: /Also mark Deferred annuity Confirmed/ })).toBeChecked();
    fireEvent.click(within(sheet).getByRole('button', { name: 'Link' }));
    expect(await screen.findByText('Linked to Deferred annuity, now Confirmed')).toBeInTheDocument();
    expect(callsTo(fetchMock, 'POST', '/api/inventory/suggestions/1/link')[0].body).toEqual({ item_id: 6, confirm: true });
    const harbor = screen.getByRole('article', { name: 'Interest from Harbor Savings Bank' });
    fireEvent.click(within(harbor).getByRole('button', { name: "Not Margaret's" }));
    expect(await screen.findByText("Not Margaret's: Harbor Savings Bank")).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole('button', { name: 'Undo' })[1]);
    expect(await screen.findByRole('article', { name: 'Interest from Harbor Savings Bank' })).toBeInTheDocument();
  });
  it('says when there is nothing to go through', async () => {
    stubFetch({ '/api/inventory/suggestions': { suggestions: [] }, '/api/inventory': { items: [], suggestions: null } });
    wrapBook(<Suggestions />, PARENT, '/b/margaret-ellis/inventory/suggestions');
    expect(await screen.findByText('Nothing to go through. New suggestions show up after a bank sync, an import or a tax form.')).toBeInTheDocument();
  });
  it('shows a viewer nothing and fetches no suggestions', async () => {
    const fetchMock = stubFetch({ '/api/inventory/suggestions': { suggestions: [S] }, '/api/inventory': { items: [], suggestions: null } });
    wrapBook(<Suggestions />, { ...PARENT, role: 'viewer' }, '/b/margaret-ellis/inventory/suggestions');
    await vi.waitFor(() => expect(screen.queryByText('Westmark Life pays Margaret $410.00 a month')).not.toBeInTheDocument());
    expect(callsTo(fetchMock, 'GET', '/api/inventory/suggestions')).toHaveLength(0);
  });
  it('shows an error with Try again when the inventory fails to load, instead of an empty picker', async () => {
    stubFetch({ '/api/inventory/suggestions': { suggestions: [S] }, '/api/inventory': () => reply({ error: 'The inventory is unavailable.' }, 500) });
    wrapBook(<Suggestions />, PARENT, '/b/margaret-ellis/inventory/suggestions');
    expect(await screen.findByText('The inventory is unavailable.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument();
  });
});
