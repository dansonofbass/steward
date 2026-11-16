import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { callsTo, expectRemovalSaid, reply, stubFetch, wrapBook } from '../../test-utils';
import CategoryRules from './CategoryRules';

afterEach(() => vi.unstubAllGlobals());

const RULES = { rules: [
  { id: 1, pattern: 'UNION SERVICE CENTER', merchant: 'Union Service Center', category: 'home', rows: 12, created_at: '2026-10-01T00:00:00+00:00', amount_cents: null, nickname: null, has_note: false },
  { id: 2, pattern: 'HARBOR GRILL', merchant: 'Harbor Grill', category: 'dining', rows: 1, created_at: '2026-09-01T00:00:00+00:00', amount_cents: null, nickname: null, has_note: false },
] };

describe('Category rules (phase 12 decision 2)', () => {
  it('lists each rule with its category and how many transactions it covers', async () => {
    stubFetch({ '/api/categorize/rules': RULES });
    wrapBook(<CategoryRules />);
    expect(await screen.findByRole('heading', { name: 'Category rules' })).toBeInTheDocument();
    const rows = await screen.findAllByRole('listitem');
    expect(rows).toHaveLength(2);
    expect(within(rows[0]).getByText('Union Service Center')).toBeInTheDocument();
    expect(within(rows[0]).getByText('UNION SERVICE CENTER')).toBeInTheDocument();
    expect(within(rows[0]).getByRole('button', { name: /^Category Home/ })).toBeInTheDocument();
    expect(within(rows[0]).getByText('12 transactions')).toBeInTheDocument();
    expect(within(rows[1]).getByText('1 transaction')).toBeInTheDocument();
  });

  it('changes a category and removes a rule, each Remove named for its rule', async () => {
    const fetchMock = stubFetch({
      '/api/categorize/rules': RULES,
      'PATCH /api/categorize/rules/1': { ...RULES.rules[0], category: 'gifts' },
      'DELETE /api/categorize/rules/2': () => new Response(null, { status: 204 }),
    });
    wrapBook(<CategoryRules />);
    const rows = await screen.findAllByRole('listitem');
    fireEvent.click(within(rows[0]).getByRole('button', { name: /^Category / }));
    fireEvent.click(within(screen.getByRole('dialog', { name: 'Category' })).getByRole('option', { name: 'Gifts' }));
    await waitFor(() => expect(callsTo(fetchMock, 'PATCH', '/api/categorize/rules/1')[0].body).toEqual({ category: 'gifts' }));
    expect(within(rows[0]).getByRole('button', { name: 'Remove rule for Union Service Center' })).toBeInTheDocument();
    await waitFor(() => expect(within(rows[1]).getByRole('button', { name: 'Remove rule for Harbor Grill' })).toBeEnabled());
    fireEvent.click(within(rows[1]).getByRole('button', { name: 'Remove rule for Harbor Grill' }));
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Remove' }));
    await waitFor(() => expect(callsTo(fetchMock, 'DELETE', '/api/categorize/rules/2')).toHaveLength(1));
  });

  it('removing a rule asks first and says past transactions stay as they are', async () => {
    const fetchMock = stubFetch({
      '/api/categorize/rules': RULES,
      'DELETE /api/categorize/rules/2': () => new Response(null, { status: 204 }),
    });
    wrapBook(<CategoryRules />);
    fireEvent.click(await screen.findByRole('button', { name: 'Remove rule for Harbor Grill' }));
    const ask = screen.getByRole('dialog', { name: 'Remove the rule for Harbor Grill?' });
    expect(within(ask).getByText("New transactions with this description won't be sorted by it. Past ones stay as they are.")).toBeInTheDocument();
    expect(callsTo(fetchMock, 'DELETE', '/api/categorize/rules')).toHaveLength(0);
    fireEvent.click(within(ask).getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(callsTo(fetchMock, 'DELETE', '/api/categorize/rules')).toHaveLength(0);
    fireEvent.click(screen.getByRole('button', { name: 'Remove rule for Harbor Grill' }));
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Remove' }));
    await waitFor(() => expect(callsTo(fetchMock, 'DELETE', '/api/categorize/rules/2')).toHaveLength(1));
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  });

  it('a double click on Remove sends one request', async () => {
    const fetchMock = stubFetch({
      '/api/categorize/rules': RULES,
      'DELETE /api/categorize/rules/2': () => new Response(null, { status: 204 }),
    });
    wrapBook(<CategoryRules />);
    fireEvent.click(await screen.findByRole('button', { name: 'Remove rule for Harbor Grill' }));
    const remove = within(screen.getByRole('dialog')).getByRole('button', { name: 'Remove' });
    fireEvent.click(remove);
    fireEvent.click(remove);
    await waitFor(() => expect(callsTo(fetchMock, 'DELETE', '/api/categorize/rules/2')).toHaveLength(1));
  });

  it('shows the server message as plain text when a write fails', async () => {
    stubFetch({
      '/api/categorize/rules': RULES,
      'DELETE /api/categorize/rules/2': () => new Response(JSON.stringify({ error: 'No such rule.' }), { status: 404, headers: { 'content-type': 'application/json' } }),
    });
    wrapBook(<CategoryRules />);
    fireEvent.click(await screen.findByRole('button', { name: 'Remove rule for Harbor Grill' }));
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Remove' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('No such rule.');
  });

  it('shows the load error, not a skeleton', async () => {
    stubFetch({ '/api/categorize/rules': () => new Response(JSON.stringify({ error: 'Steward could not load the rules.' }), { status: 500, headers: { 'content-type': 'application/json' } }) });
    wrapBook(<CategoryRules />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Steward could not load the rules.');
  });

  it('shows the pattern alone when a rule has no merchant', async () => {
    stubFetch({ '/api/categorize/rules': { rules: [{ ...RULES.rules[0], merchant: null }] } });
    wrapBook(<CategoryRules />);
    const row = await screen.findByRole('listitem');
    expect(within(row).getByText('UNION SERVICE CENTER')).toBeInTheDocument();
    expect(within(row).getByRole('button', { name: 'Remove rule for UNION SERVICE CENTER' })).toBeInTheDocument();
  });

  it('says what happens when there are none', async () => {
    stubFetch({ '/api/categorize/rules': { rules: [] } });
    wrapBook(<CategoryRules />);
    expect(await screen.findByText('When you sort a transaction, Steward remembers it here.')).toBeInTheDocument();
  });

  it('an amount rule shows its amount and name, a note only as "has a note", and a names-only rule says so', async () => {
    stubFetch({ '/api/categorize/rules': { rules: [{ id: 9, pattern: 'PAYPAL', merchant: 'PayPal', category: null, rows: 12,
      created_at: '2026-10-28T00:00:00+00:00', amount_cents: -1399, nickname: 'Disney+', has_note: true }] } });
    wrapBook(<CategoryRules />);
    const row = (await screen.findByText('PAYPAL · $13.99 · Disney+ · has a note')).closest('li')!;
    expect(row).toHaveTextContent('Names only');
    expect(within(row).queryByRole('button', { name: /^Category/ })).toBeNull();
  });

  it('after removing a rule, says which and keeps focus on the page, not the gone row (THO-1)', async () => {
    let rules = RULES;
    stubFetch({ '/api/categorize/rules': () => reply(rules),
      'DELETE /api/categorize/rules/2': () => { rules = { rules: [RULES.rules[0]] }; return new Response(null, { status: 204 }); } });
    wrapBook(<CategoryRules />);
    const button = await screen.findByRole('button', { name: 'Remove rule for Harbor Grill' });
    await waitFor(() => expect(button).toBeEnabled());
    button.focus();
    fireEvent.click(button);
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Remove' }));
    await expectRemovalSaid('Removed the rule for Harbor Grill.', () => screen.getByRole('heading', { name: 'Category rules' }));
  });
});
