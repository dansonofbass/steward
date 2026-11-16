import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { callsTo, renderAt, reply, stubFetch } from '../../test-utils';
import { TARGETS, TARGETS_FIRST } from './fixtures';
import { Targets } from './Targets';

afterEach(() => vi.unstubAllGlobals());
const rowOf = (c: string) => screen.getAllByTestId('target-row').find((r) => r.getAttribute('data-category') === c)!;
const everyday = () => screen.getByRole('region', { name: 'Flexible' });
const saveIn = (name: string | RegExp) => within(screen.getByRole('region', { name })).getByRole('button', { name: 'Save targets' });

describe('Set targets', () => {
  it('lists everyday categories in the fixed order with their typical months, and says who changed them last', async () => {
    stubFetch({ '/api/spending/targets': TARGETS });
    renderAt(<Targets />, {}, '/spending/targets');
    await screen.findByTestId('sumcard');   // the h1 is there while it loads too
    expect(screen.getByRole('heading', { level: 1, name: 'Set targets' })).toBeInTheDocument();
    expect(screen.getByText('Targets last changed by Alex on Sep 30.')).toBeInTheDocument();
    expect(within(everyday()).getAllByTestId('target-row').map((r) => r.getAttribute('data-category')).slice(0, 8))
      .toEqual(['groceries', 'dining', 'transport', 'shopping', 'home', 'kids', 'health', 'entertainment']);
    expect(screen.getByRole('textbox', { name: 'Groceries target' })).toHaveValue('1,300');
    expect(rowOf('groceries')).toHaveTextContent('Typical month $1,240');
    expect(rowOf('travel')).toHaveTextContent('Nothing most months');
    expect(rowOf('utilities')).toHaveTextContent('About $410 · $360 to $560');
    expect(rowOf('housing')).toHaveTextContent('Same every month');
    expect(screen.getByRole('textbox', { name: 'Housing expected' })).toHaveAttribute('placeholder', 'Typical');
    const sum = screen.getByTestId('sumcard');
    expect(sum).toHaveTextContent('Flexible targets$3,550');
    expect(sum).toHaveTextContent('Fixed costs, about$4,590');
    expect(sum).toHaveTextContent('A month$8,140');
    expect(sum).toHaveTextContent('Typical income$10,200');
    expect(sum).toHaveTextContent('Leaves about $2,060 a month.');
    expect(screen.queryByRole('region', { name: /change/ })).toBeNull();
  });

  it('a changed target is outlined, offers the typical month, and saves only what changed', async () => {
    const saved = { ...TARGETS, categories: TARGETS.categories.map((r) => (r.category === 'groceries' ? { ...r, monthly_cents: 124_000 } : r)), updated_by: 'JR' };
    let current = TARGETS;   // the refetch after the save answers with what was saved, as the server would
    const fetchMock = stubFetch({ '/api/spending/targets': () => reply(current), 'PUT /api/spending/targets': () => { current = saved; return reply(saved); } });
    const { qc } = renderAt(<Targets />, {}, '/spending/targets');
    const input = await screen.findByRole('textbox', { name: 'Groceries target' });
    expect(screen.getByText('Suggestions leave room: 3 of 4 recent months came in at or under them.')).toBeInTheDocument();
    fireEvent.change(input, { target: { value: '1250' } });
    const bar = screen.getByRole('region', { name: '1 change' });
    expect(bar).toHaveTextContent('Groceries $1,300 → $1,250');
    expect(input.closest('.sp-trow__input')).toHaveClass('is-changed');
    fireEvent.click(within(rowOf('groceries')).getByRole('button', { name: 'Use $1,240' }));
    expect(input).toHaveValue('1,240');
    const spy = vi.spyOn(qc, 'invalidateQueries');
    fireEvent.click(saveIn('1 change'));
    expect(await screen.findByText('Targets saved.')).toBeInTheDocument();
    expect(callsTo(fetchMock, 'PUT', '/api/spending/targets')[0].body).toEqual({
      targets: [{ category: 'groceries', kind: 'everyday', monthly_cents: 124_000 }] });
    expect(spy).toHaveBeenCalledWith({ queryKey: ['spending'] });
    expect(screen.queryByRole('region', { name: /change/ })).toBeNull();
  });

  it('a kind moves a row to its card, and saves alone', async () => {
    const fetchMock = stubFetch({ '/api/spending/targets': TARGETS, 'PUT /api/spending/targets': TARGETS });
    renderAt(<Targets />, {}, '/spending/targets');
    fireEvent.change(await screen.findByRole('combobox', { name: 'Kind of Subscriptions' }), { target: { value: 'everyday' } });
    expect(within(everyday()).getAllByTestId('target-row').map((r) => r.getAttribute('data-category'))).toContain('subscriptions');
    const bar = screen.getByRole('region', { name: '1 change' });
    expect(bar).toHaveTextContent('Subscriptions bill → flexible');
    fireEvent.click(within(bar).getByRole('button', { name: 'Save targets' }));
    await waitFor(() => expect(callsTo(fetchMock, 'PUT', '/api/spending/targets')).toHaveLength(1));
    expect(callsTo(fetchMock, 'PUT', '/api/spending/targets')[0].body).toEqual({ targets: [{ category: 'subscriptions', kind: 'everyday', monthly_cents: null }] });
    expect(screen.queryByRole('textbox', { name: 'Percent ahead' })).toBeNull();
  });

  it('an amount it cannot read is named and cannot be saved; Reset puts everything back', async () => {
    stubFetch({ '/api/spending/targets': TARGETS });
    renderAt(<Targets />, {}, '/spending/targets');
    fireEvent.change(await screen.findByRole('textbox', { name: 'Eating out target' }), { target: { value: '12.345' } });
    const bar = screen.getByRole('region', { name: 'Eating out: Use at most two decimals.' });
    expect(within(bar).getByRole('button', { name: 'Save targets' })).toBeDisabled();
    fireEvent.click(within(bar).getByRole('button', { name: 'Reset' }));
    expect(screen.getByRole('textbox', { name: 'Eating out target' })).toHaveValue('500');
    expect(screen.queryByRole('region', { name: /Eating out:/ })).toBeNull();
  });

  it('the first time, Use these targets saves every everyday suggestion at once', async () => {
    let current = TARGETS_FIRST;
    const fetchMock = stubFetch({ '/api/spending/targets': () => reply(current), 'PUT /api/spending/targets': () => { current = TARGETS; return reply(TARGETS); } });
    renderAt(<Targets />, {}, '/spending/targets');
    expect(await screen.findByText('Suggested from the last 6 months')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Use these targets' }));
    await waitFor(() => expect(callsTo(fetchMock, 'PUT', '/api/spending/targets')).toHaveLength(1));
    const body = callsTo(fetchMock, 'PUT', '/api/spending/targets')[0].body as { targets: { category: string; monthly_cents: number }[] };
    expect(body.targets.map((t) => [t.category, t.monthly_cents])).toEqual([
      ['groceries', 124_000], ['dining', 47_000], ['transport', 44_000], ['shopping', 39_000], ['home', 29_000],
      ['kids', 23_000], ['health', 18_000], ['entertainment', 12_000], ['personal', 9_000], ['gifts', 6_000]]);
    expect(await screen.findByText('Targets saved.')).toBeInTheDocument();
    expect(screen.queryByText('Suggested from the last 6 months')).toBeNull();
  });

  it('Adjust first fills the suggestions in without saving', async () => {
    const fetchMock = stubFetch({ '/api/spending/targets': TARGETS_FIRST });
    renderAt(<Targets />, {}, '/spending/targets');
    fireEvent.click(await screen.findByRole('button', { name: 'Adjust first' }));
    expect(screen.getByRole('textbox', { name: 'Groceries target' })).toHaveValue('1,240');
    // Engineering choice 10: a fixed cost keeps "Typical" until someone types an amount.
    expect(screen.getByRole('textbox', { name: 'Housing expected' })).toHaveValue('');
    expect(screen.queryByText('Suggested from the last 6 months')).toBeNull();
    expect(screen.getByRole('region', { name: '10 changes' })).toBeInTheDocument();
    expect(callsTo(fetchMock, 'PUT', '/api/spending/targets')).toHaveLength(0);
  });

  it('Accept all suggestions fills the draft; Save commits it', async () => {
    const fetchMock = stubFetch({ '/api/spending/targets': TARGETS, 'PUT /api/spending/targets': TARGETS });
    renderAt(<Targets />, {}, '/spending/targets');
    fireEvent.click(await screen.findByRole('button', { name: 'Accept all suggestions' }));
    expect(screen.getByRole('textbox', { name: 'Groceries target' })).toHaveValue('1,240');
    expect(screen.getByRole('textbox', { name: 'Housing expected' })).toHaveValue('');
    expect(callsTo(fetchMock, 'PUT', '/api/spending/targets')).toHaveLength(0);
    fireEvent.click(saveIn('10 changes'));
    await waitFor(() => expect(callsTo(fetchMock, 'PUT', '/api/spending/targets')).toHaveLength(1));
  });

  it('a viewer reads the targets with nothing to change', async () => {
    stubFetch({ '/api/spending/targets': TARGETS });
    renderAt(<Targets />, { role: 'viewer' }, '/spending/targets');
    await screen.findByTestId('sumcard');
    expect(screen.queryAllByRole('textbox')).toHaveLength(0);
    expect(screen.queryAllByRole('combobox')).toHaveLength(0);
    expect(screen.queryByRole('button', { name: 'Accept all suggestions' })).toBeNull();
    expect(rowOf('groceries')).toHaveTextContent('$1,300');
  });

  it('a viewer gets no first-time notice, no buttons and no save bar', async () => {
    stubFetch({ '/api/spending/targets': TARGETS_FIRST });
    renderAt(<Targets />, { role: 'viewer' }, '/spending/targets');
    await screen.findByTestId('sumcard');
    expect(screen.queryByText('Suggested from the last 6 months')).toBeNull();
    expect(screen.queryAllByRole('button')).toHaveLength(0);
    expect(screen.queryByRole('region', { name: /change/ })).toBeNull();
  });

  // Ruling 25: every amount is checked against the server's bounds, at its field, before anything is sent.
  it('a target over $1,000,000 is a field error and cannot be saved', async () => {
    const fetchMock = stubFetch({ '/api/spending/targets': TARGETS });
    renderAt(<Targets />, {}, '/spending/targets');
    const input = await screen.findByRole('textbox', { name: 'Groceries target' });
    fireEvent.change(input, { target: { value: '1000001' } });
    const message = 'Enter a target from $0 to $1,000,000, or leave it blank.';
    expect(input).toHaveAttribute('aria-invalid', 'true');
    expect(input).toHaveAccessibleDescription(message);
    expect(saveIn(`Groceries: ${message}`)).toBeDisabled();
    expect(callsTo(fetchMock, 'PUT', '/api/spending/targets')).toHaveLength(0);
  });

  it("the server's refusal is shown, and the draft is kept", async () => {
    stubFetch({ '/api/spending/targets': TARGETS, 'PUT /api/spending/targets': () => reply({ error: 'Warn at $0 to $1,000 ahead.' }, 422) });
    renderAt(<Targets />, {}, '/spending/targets');
    const input = await screen.findByRole('textbox', { name: 'Groceries target' });
    fireEvent.change(input, { target: { value: '1250' } });
    fireEvent.click(saveIn('1 change'));
    expect(await screen.findByRole('alert')).toHaveTextContent('Warn at $0 to $1,000 ahead.');
    expect(input).toHaveValue('1,250');
    expect(screen.getByRole('region', { name: '1 change' })).toBeInTheDocument();
    expect(screen.queryByText('Targets saved.')).toBeNull();
  });

  it('an explicit $0 saves as 0, and a cleared field saves no target (ruling 21)', async () => {
    const fetchMock = stubFetch({ '/api/spending/targets': TARGETS, 'PUT /api/spending/targets': TARGETS });
    renderAt(<Targets />, {}, '/spending/targets');
    fireEvent.change(await screen.findByRole('textbox', { name: 'Groceries target' }), { target: { value: '' } });
    fireEvent.change(screen.getByRole('textbox', { name: 'Housing expected' }), { target: { value: '0' } });
    fireEvent.click(saveIn('2 changes'));
    await waitFor(() => expect(callsTo(fetchMock, 'PUT', '/api/spending/targets')).toHaveLength(1));
    expect((callsTo(fetchMock, 'PUT', '/api/spending/targets')[0].body as { targets: unknown[] }).targets).toEqual([
      { category: 'groceries', kind: 'everyday', monthly_cents: null }, { category: 'housing', kind: 'fixed', monthly_cents: 0 }]);
  });

  it('a row made once in a while loses its amount field and sends no amount', async () => {
    const fetchMock = stubFetch({ '/api/spending/targets': TARGETS, 'PUT /api/spending/targets': TARGETS });
    renderAt(<Targets />, {}, '/spending/targets');
    fireEvent.change(await screen.findByRole('combobox', { name: 'Kind of Groceries' }), { target: { value: 'occasional' } });
    expect(screen.queryByRole('textbox', { name: /^Groceries/ })).toBeNull();
    expect(within(screen.getByRole('region', { name: 'Once in a while' })).getAllByTestId('target-row').map((r) => r.getAttribute('data-category')))
      .toEqual(['groceries', 'taxes']);
    expect(screen.getByTestId('sumcard')).toHaveTextContent('Flexible targets$2,250');
    fireEvent.click(saveIn('1 change'));
    await waitFor(() => expect(callsTo(fetchMock, 'PUT', '/api/spending/targets')).toHaveLength(1));
    expect((callsTo(fetchMock, 'PUT', '/api/spending/targets')[0].body as { targets: unknown[] }).targets).toEqual([
      { category: 'groceries', kind: 'occasional', monthly_cents: null }]);
  });

  it('a kind-only save keeps the first-time notice: nothing has an amount yet (ruling 11)', async () => {
    const saved = { ...TARGETS_FIRST, categories: TARGETS_FIRST.categories.map((r) => (r.category === 'subscriptions' ? { ...r, kind: 'everyday' as const } : r)) };
    let current = TARGETS_FIRST;
    stubFetch({ '/api/spending/targets': () => reply(current), 'PUT /api/spending/targets': () => { current = saved; return reply(saved); } });
    renderAt(<Targets />, {}, '/spending/targets');
    fireEvent.change(await screen.findByRole('combobox', { name: 'Kind of Subscriptions' }), { target: { value: 'everyday' } });
    fireEvent.click(saveIn('1 change'));
    expect(await screen.findByText('Targets saved.')).toBeInTheDocument();
    expect(screen.getByText('Suggested from the last 6 months')).toBeInTheDocument();
  });

  it('a save in flight cannot be sent twice', async () => {
    let answer: (r: Response) => void = () => {};
    const fetchMock = stubFetch({ '/api/spending/targets': TARGETS, 'PUT /api/spending/targets': () => new Promise<Response>((res) => { answer = res; }) });
    renderAt(<Targets />, {}, '/spending/targets');
    fireEvent.change(await screen.findByRole('textbox', { name: 'Groceries target' }), { target: { value: '1250' } });
    const save = saveIn('1 change');
    fireEvent.click(save);
    fireEvent.click(save);
    expect(save).toHaveAttribute('aria-busy', 'true');
    expect(within(screen.getByRole('region', { name: '1 change' })).getByRole('button', { name: 'Reset' })).toBeDisabled();
    await waitFor(() => expect(callsTo(fetchMock, 'PUT', '/api/spending/targets')).toHaveLength(1));
    answer(reply(TARGETS));
    expect(await screen.findByText('Targets saved.')).toBeInTheDocument();
    expect(callsTo(fetchMock, 'PUT', '/api/spending/targets')).toHaveLength(1);
  });

  it('a failed Use these targets keeps the suggestions in the draft and says why', async () => {
    stubFetch({ '/api/spending/targets': TARGETS_FIRST, 'PUT /api/spending/targets': () => reply({ error: 'Something broke.' }, 500) });
    renderAt(<Targets />, {}, '/spending/targets');
    fireEvent.click(await screen.findByRole('button', { name: 'Use these targets' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Something broke.');
    expect(screen.getByRole('textbox', { name: 'Groceries target' })).toHaveValue('1,240');
    expect(screen.getByRole('region', { name: '10 changes' })).toBeInTheDocument();
  });

  it("new targets from the server replace a draft with nothing in it, and leave one with changes as typed", async () => {
    stubFetch({ '/api/spending/targets': TARGETS });
    const { qc } = renderAt(<Targets />, {}, '/spending/targets');
    const groceries = await screen.findByRole('textbox', { name: 'Groceries target' });
    const theirs = (dining: number) => ({ ...TARGETS, categories: TARGETS.categories.map((r) => (r.category === 'dining' ? { ...r, monthly_cents: dining } : r)) });
    act(() => { qc.setQueryData(['spending', 'targets'], theirs(55_000)); });
    await waitFor(() => expect(screen.getByRole('textbox', { name: 'Eating out target' })).toHaveValue('550'));
    expect(screen.queryByRole('region', { name: /change/ })).toBeNull();
    fireEvent.change(groceries, { target: { value: '1250' } });
    act(() => { qc.setQueryData(['spending', 'targets'], theirs(60_000)); });
    expect(await screen.findByRole('region', { name: '2 changes' })).toHaveTextContent('Groceries $1,300 → $1,250 · Eating out $600 → $550');
    expect(groceries).toHaveValue('1,250');
  });

  // Fix round 1: a book with no history has nothing to suggest, so no notice says Steward filled anything in.
  const NO_HISTORY = { ...TARGETS_FIRST, categories: TARGETS_FIRST.categories.map((r) => ({ ...r, typical_cents: null, suggested_cents: null, low_cents: null, high_cents: null })) };

  it('a book without history says suggestions come later, instead of offering ones it does not have', async () => {
    const fetchMock = stubFetch({ '/api/spending/targets': NO_HISTORY });
    renderAt(<Targets />, {}, '/spending/targets');
    expect(await screen.findByText("Targets can be suggested once there's a month of history.")).toBeInTheDocument();
    expect(screen.queryByText('Suggested from the last 6 months')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Use these targets' })).toBeNull();
    expect(callsTo(fetchMock, 'PUT', '/api/spending/targets')).toHaveLength(0);
  });

  it('a book with targets but no history offers no suggestions to accept', async () => {
    stubFetch({ '/api/spending/targets': { ...NO_HISTORY, has_targets: true, categories: NO_HISTORY.categories.map((r) => (r.category === 'groceries' ? { ...r, monthly_cents: 130_000 } : r)) } });
    renderAt(<Targets />, {}, '/spending/targets');
    await screen.findByTestId('sumcard');
    expect(screen.queryByRole('button', { name: 'Accept all suggestions' })).toBeNull();
    expect(screen.queryByText("Targets can be suggested once there's a month of history.")).toBeNull();
  });

  it('a save with nothing in it sends nothing and never says it saved', async () => {
    // Every suggestion is already the saved amount, so Use these targets has nothing to change. (Ruling 11 makes this
    // state rare; the guard is in save, so no path can PUT an empty change and announce it.)
    const filled = { ...TARGETS_FIRST, categories: TARGETS_FIRST.categories.map((r) => ({ ...r, monthly_cents: r.kind === 'everyday' ? r.suggested_cents : null })) };
    const fetchMock = stubFetch({ '/api/spending/targets': filled, 'PUT /api/spending/targets': filled });
    renderAt(<Targets />, {}, '/spending/targets');
    fireEvent.click(await screen.findByRole('button', { name: 'Use these targets' }));
    await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
    expect(callsTo(fetchMock, 'PUT', '/api/spending/targets')).toHaveLength(0);
    expect(screen.queryByText('Targets saved.')).toBeNull();
    expect(screen.queryByRole('region', { name: /change/ })).toBeNull();
  });

  it('Use these targets with a field it cannot read keeps the notice and takes you to that field (M2)', async () => {
    const fetchMock = stubFetch({ '/api/spending/targets': TARGETS_FIRST });
    renderAt(<Targets />, {}, '/spending/targets');
    const housing = await screen.findByRole('textbox', { name: 'Housing expected' });
    fireEvent.change(housing, { target: { value: '12.345' } });
    fireEvent.click(screen.getByRole('button', { name: 'Use these targets' }));
    expect(housing).toHaveFocus();
    expect(housing).toHaveAccessibleDescription('Use at most two decimals.');
    expect(screen.getByText('Suggested from the last 6 months')).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'Groceries target' })).toHaveValue('1,240');
    expect(callsTo(fetchMock, 'PUT', '/api/spending/targets')).toHaveLength(0);
  });

  it('Kept targets lists each kept target, and Check again asks again, with Undo', async () => {
    const kept = { ...TARGETS, kept: [{ category: 'dining', target_cents: 50_000, until: '2027-01-01' }] };
    const fetchMock = stubFetch({ '/api/spending/targets': kept, 'DELETE /api/spending/targets/dining/kept': { undo: 'tok-a' }, 'POST /api/undo/tok-a': { undone: 0, transaction: null } });
    renderAt(<Targets />, {}, '/spending/targets');
    expect(await screen.findByText('Kept targets')).toBeInTheDocument();
    const row = screen.getByTestId('kept-row');
    expect(row).toHaveTextContent('Eating out · $500, kept until Jan');
    fireEvent.click(within(row).getByRole('button', { name: 'Check again' }));
    expect(await screen.findByRole('status')).toHaveTextContent('Eating out will be checked again · Undo');
    expect(callsTo(fetchMock, 'DELETE', '/api/spending/targets/dining/kept')).toHaveLength(1);
    fireEvent.click(screen.getByRole('button', { name: 'Undo' }));
    await waitFor(() => expect(callsTo(fetchMock, 'POST', '/api/undo/tok-a')).toHaveLength(1));
  });

  it('says which categories are not spending: business income is one, business expense is not (ruling 27)', async () => {
    stubFetch({ '/api/spending/targets': TARGETS });
    renderAt(<Targets />, {}, '/spending/targets');
    expect(await screen.findByText('Income, business income, interest, transfers and Not sorted yet are not spending categories and have no target.')).toBeInTheDocument();
    expect(rowOf('business_expense')).toBeInTheDocument();
  });

  it('names the page while it loads and when the targets cannot be loaded', async () => {
    stubFetch({ '/api/spending/targets': () => reply({ error: 'Something broke.' }, 500) });
    renderAt(<Targets />, {}, '/spending/targets');
    expect(screen.getByRole('heading', { level: 1, name: 'Set targets' })).toBeInTheDocument();
    expect(await screen.findByText('Something broke.')).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 1, name: 'Set targets' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument();
  });
});
