import { fireEvent, screen, within } from '@testing-library/react';
import { Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { callsTo, reply, stubFetch, wrapBook } from '../../test-utils';
import type { ItemRow } from './api';
import { ItemForm } from './ItemForm';

afterEach(() => vi.unstubAllGlobals());
const OWNERS = [{ key: 'margaret', label: 'Margaret' }, { key: 'robert-husband', label: 'Robert (husband)' }, { key: 'joint', label: 'Joint' }];
const PARENT = { slug: 'margaret-ellis', name: 'Margaret Ellis', kind: 'parent' as const, owners: OWNERS };
const CHECKING = { id: 1, kind: 'account', name: 'Joint checking', institution: 'Wells Fargo', last4: '4417', status: 'confirmed' } as ItemRow;
const mount = (path: string) => wrapBook(
  <Routes><Route path="/b/:slug/inventory/new" element={<ItemForm />} /><Route path="/b/:slug/inventory/:id/edit" element={<ItemForm />} /></Routes>,
  PARENT, path);
const change = (label: string, value: string) => fireEvent.change(screen.getByLabelText(label), { target: { value } });

describe('Item form', () => {
  it('adds a policy with its premium and why it needs checking', async () => {
    const fetchMock = stubFetch({ '/api/inventory': { items: [CHECKING], suggestions: null }, 'POST /api/inventory/items': () => reply({ id: 9 }, 201) });
    mount('/b/margaret-ellis/inventory/new?kind=insurance');
    expect(await screen.findByRole('heading', { name: 'Add an item' })).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: 'Insurance' })).toHaveAttribute('aria-checked', 'true');
    change('Type', 'supplement');
    change('Name', 'Medicare supplement');
    change('Insurer', 'Globe Mutual');
    change('Policy number', 'GM-55120-0861');
    expect(screen.getByText('Lists and emails show only the last 4: ••0861.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('radio', { name: 'Margaret' }));
    change('Amount', '186.20');
    change('Paid from', '1');
    change('Usual day of the month', '15');
    fireEvent.click(screen.getByRole('radio', { name: /Needs checking/ }));
    change('Why it needs checking', 'From a premium notice');
    fireEvent.click(screen.getByRole('button', { name: 'Add item' }));
    await vi.waitFor(() => expect(callsTo(fetchMock, 'POST', '/api/inventory/items')).toHaveLength(1));
    expect(callsTo(fetchMock, 'POST', '/api/inventory/items')[0].body).toEqual({
      kind: 'insurance', name: 'Medicare supplement', owner: 'margaret', institution: 'Globe Mutual', login_kept_in: null,
      notes: null, status: 'needs_checking', check_reason: 'From a premium notice', number: 'GM-55120-0861',
      details: { type: 'supplement', amount_cents: 18620, frequency: 'monthly', paid_from_id: 1, usual_day: 15, match_text: null, renewal_on: null },
    });
  });
  it('fills itself in from a suggestion and answers it', async () => {
    const prefill = { kind: 'insurance', name: 'Medicare supplement', institution: 'Globe Mutual', owner: 'joint', status: 'needs_checking',
      check_reason: 'Suggested from 4 payments in Margaret\'s transactions.', data_source: 'feed',
      details: { type: 'supplement', amount_cents: 18620, frequency: 'monthly', usual_day: 15, paid_from_id: 1, match_text: 'GLOBE MUTUAL MEDSUPP PREM' } };
    const fetchMock = stubFetch({
      '/api/inventory/suggestions': { suggestions: [{ id: 7, prefill, filled_line: 'Filled in from 4 Globe Mutual payments. Check each field, then Add item.' }] },
      '/api/inventory': { items: [CHECKING], suggestions: null }, 'POST /api/inventory/items': () => reply({ id: 9 }, 201),
    });
    mount('/b/margaret-ellis/inventory/new?suggestion=7');
    expect(await screen.findByText('Filled in from 4 Globe Mutual payments. Check each field, then Add item.')).toBeInTheDocument();
    expect(screen.getByLabelText('Name')).toHaveValue('Medicare supplement');
    expect(screen.getByLabelText('Amount')).toHaveValue('186.2');   // dollarsText drops a trailing zero, as Settings does
    fireEvent.click(screen.getByRole('button', { name: 'Add item' }));
    await vi.waitFor(() => expect(callsTo(fetchMock, 'POST', '/api/inventory/items')).toHaveLength(1));
    const body = callsTo(fetchMock, 'POST', '/api/inventory/items')[0].body as Record<string, unknown>;
    expect([body.suggestion_id, body.data_source, body.owner]).toEqual([7, 'feed', 'joint']);
  });
  it('edits with a reason, keeps a blank number, and closes the item', async () => {
    const detail = { ...CHECKING, id: 12, kind: 'insurance', name: 'Long-term care', owner: 'margaret', institution: 'Evergreen Mutual',
      last4: '7730', status: 'needs_checking', check_reason: 'From a notice', data_source: 'manual', login_kept_in: null, notes: null,
      has_full_number: true, details: { type: 'long_term_care', amount_cents: 21200, frequency: 'monthly', usual_day: 10, paid_from_id: 1 } };
    const fetchMock = stubFetch({
      '/api/inventory/items/12': detail, '/api/inventory': { items: [CHECKING], suggestions: null },
      'PATCH /api/inventory/items/12': () => reply(detail), 'POST /api/inventory/items/12/close': () => reply(detail),
    });
    mount('/b/margaret-ellis/inventory/12/edit');
    expect(await screen.findByRole('heading', { name: 'Edit Long-term care' })).toBeInTheDocument();
    expect(screen.getByText('Leave blank to keep ••7730.')).toBeInTheDocument();
    expect(screen.queryByRole('radiogroup', { name: 'Kind' })).toBeNull();
    change('Renewal date', '2027-03-01');
    change('Why the change? (optional)', 'Policy letter arrived Oct 18');
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await vi.waitFor(() => expect(callsTo(fetchMock, 'PATCH', '/api/inventory/items/12')).toHaveLength(1));
    const body = callsTo(fetchMock, 'PATCH', '/api/inventory/items/12')[0].body as Record<string, unknown>;
    expect(body.number).toBeUndefined();
    expect(body.kind).toBeUndefined();
    expect(body.note).toBe('Policy letter arrived Oct 18');
    expect((body.details as Record<string, unknown>).renewal_on).toBe('2027-03-01');
    fireEvent.click(screen.getByRole('button', { name: 'Close this item' }));
    const box = screen.getByRole('group', { name: 'Close Long-term care?' });
    fireEvent.change(within(box).getByLabelText('Closed on'), { target: { value: '2026-10-18' } });
    fireEvent.change(within(box).getByLabelText('Why'), { target: { value: 'Policy cancelled' } });
    fireEvent.click(within(box).getByRole('button', { name: 'Close item' }));
    await vi.waitFor(() => expect(callsTo(fetchMock, 'POST', '/api/inventory/items/12/close')).toHaveLength(1));
    expect(callsTo(fetchMock, 'POST', '/api/inventory/items/12/close')[0].body).toEqual({ closed_on: '2026-10-18', why: 'Policy cancelled' });
  });
  it('a contact has no How sure question and the server\'s refusal is shown', async () => {
    const fetchMock = stubFetch({ '/api/inventory': { items: [CHECKING], suggestions: null },
      'POST /api/inventory/items': () => reply({ error: 'Choose their role.' }, 422) });
    mount('/b/margaret-ellis/inventory/new?kind=contact');
    expect(await screen.findByLabelText('Role')).toBeInTheDocument();
    expect(screen.queryByText('How sure are we?')).toBeNull();
    change('Name', 'Linda Park');
    fireEvent.click(screen.getByRole('button', { name: 'Add item' }));
    expect(await screen.findByText('Choose their role.')).toBeInTheDocument();
    expect((callsTo(fetchMock, 'POST', '/api/inventory/items')[0].body as Record<string, unknown>).status).toBeUndefined();
  });
  it('sends a viewer away to the inventory', async () => {
    stubFetch({ '/api/inventory': { items: [CHECKING], suggestions: null } });
    wrapBook(
      <Routes><Route path="/b/:slug/inventory/new" element={<ItemForm />} /><Route path="/b/:slug/inventory" element={<p>The list</p>} /></Routes>,
      { ...PARENT, role: 'viewer' as const }, '/b/margaret-ellis/inventory/new');
    expect(await screen.findByText('The list')).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Add an item' })).toBeNull();
  });
  it('sets a low-balance floor on a savings account', async () => {
    const SAVINGS = { id: 2, kind: 'account', name: 'Way2Save savings', owner: 'joint', institution: 'Wells Fargo', last4: '4425',
      status: 'confirmed', data_source: 'feed', details: { type: 'savings' } };
    const fetchMock = stubFetch({ '/api/inventory/items/2': SAVINGS, '/api/inventory': { items: [], suggestions: null },
      'PATCH /api/inventory/items/2': () => reply(SAVINGS) });
    mount('/b/margaret-ellis/inventory/2/edit');
    fireEvent.change(await screen.findByLabelText('Low-balance floor'), { target: { value: '25,000.00' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await vi.waitFor(() => expect(callsTo(fetchMock, 'PATCH', '/api/inventory/items/2')).toHaveLength(1));
    expect((callsTo(fetchMock, 'PATCH', '/api/inventory/items/2')[0].body as { details: Record<string, unknown> }).details)
      .toEqual({ type: 'savings', floor_cents: 2500000 });
  });
  it('shows a failed close inside the close box, where the person is looking', async () => {
    const detail = { ...CHECKING, id: 12, kind: 'insurance', name: 'Long-term care', owner: 'margaret', institution: 'Evergreen Mutual',
      last4: '7730', status: 'confirmed', check_reason: null, data_source: 'manual', login_kept_in: null, notes: null,
      has_full_number: true, details: { type: 'long_term_care', frequency: 'monthly' } };
    stubFetch({ '/api/inventory/items/12': detail, '/api/inventory': { items: [CHECKING], suggestions: null },
      'POST /api/inventory/items/12/close': () => reply({ error: 'It was closed already.' }, 409) });
    mount('/b/margaret-ellis/inventory/12/edit');
    fireEvent.click(await screen.findByRole('button', { name: 'Close this item' }));
    const box = screen.getByRole('group', { name: 'Close Long-term care?' });
    fireEvent.click(within(box).getByRole('button', { name: 'Close item' }));
    expect(await within(box).findByText('It was closed already.')).toBeInTheDocument();
  });
  it('says so when the suggestion in the link is gone, and still offers the blank form', async () => {
    stubFetch({ '/api/inventory/suggestions': { suggestions: [] }, '/api/inventory': { items: [CHECKING], suggestions: null } });
    mount('/b/margaret-ellis/inventory/new?suggestion=99');
    expect(await screen.findByText(/That suggestion isn't here any more/)).toBeInTheDocument();
    expect(screen.getByLabelText('Name')).toHaveValue('');
  });
  it('switching kind drops fields that belong to the old kind', async () => {
    stubFetch({ '/api/inventory': { items: [CHECKING], suggestions: null } });
    mount('/b/margaret-ellis/inventory/new?kind=insurance');
    await screen.findByRole('heading', { name: 'Add an item' });
    change('Name', 'Medicare supplement');
    change('Amount', '186.20');
    change('How often', 'half_yearly');
    fireEvent.click(screen.getByRole('radio', { name: 'Income' }));
    expect(screen.getByLabelText('Name')).toHaveValue('Medicare supplement');
    expect(screen.getByRole('textbox', { name: 'Amount' })).toHaveValue('');
    expect(screen.getByLabelText('How often')).toHaveValue('monthly');
  });

  it('adds the benefit terms of a long-term care policy', async () => {
    const fetchMock = stubFetch({ '/api/inventory': { items: [CHECKING], suggestions: null }, 'POST /api/inventory/items': () => reply({ id: 9 }, 201) });
    mount('/b/margaret-ellis/inventory/new?kind=insurance');
    expect(await screen.findByRole('heading', { name: 'Add an item' })).toBeInTheDocument();
    change('Type', 'long_term_care');
    change('Name', 'Long-term care');
    fireEvent.click(screen.getByRole('radio', { name: 'Margaret' }));
    change('Amount', '212');
    change('Benefit', '150');
    change('Waiting period, days', '90');
    change('Benefit years', '3');
    change('Inflation protection, % a year', '3');
    fireEvent.click(screen.getByRole('button', { name: 'Add item' }));
    await vi.waitFor(() => expect(callsTo(fetchMock, 'POST', '/api/inventory/items')).toHaveLength(1));
    const body = callsTo(fetchMock, 'POST', '/api/inventory/items')[0].body as { details: Record<string, unknown> };
    expect(body.details).toMatchObject({ type: 'long_term_care', amount_cents: 21200, benefit_cents: 15000, benefit_per: 'day',
      waiting_days: 90, pool_cents: null, benefit_years: 3, rider_bp: 300 });
  });

  it('asks for a pension or annuity before tax is withheld, since Care works out the tax', async () => {
    stubFetch({ '/api/inventory': { items: [CHECKING], suggestions: null } });
    mount('/b/margaret-ellis/inventory/new?kind=income');
    expect(await screen.findByRole('heading', { name: 'Add an item' })).toBeInTheDocument();
    for (const source of ['pension', 'annuity']) {
      change('Source', source);
      expect(screen.getByLabelText('Amount before tax is withheld')).toBeInTheDocument();
    }
    change('Source', 'social_security');
    expect(within(screen.getByRole('region', { name: 'Amount' })).getByLabelText('Amount')).toHaveAttribute('inputmode', 'decimal');
    expect(screen.queryByLabelText('Amount before tax is withheld')).toBeNull();
  });
});
