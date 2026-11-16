import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { SetAsideList } from '../../../api/types';
import { useFakeTimers } from '../../../test-clock';
import { callsTo, renderAt, reply, stubFetch } from '../../../test-utils';
import { LIST } from './fixtures';
import { SetAsides } from './SetAsides';

afterEach(() => vi.unstubAllGlobals());
// The first findBy pays jsdom and React warm-up; on fake timers its ceiling is fake time, not the machine's load (W4).
beforeEach(() => { useFakeTimers(); });
const rows = () => screen.getAllByTestId('sa-suggestion');
const box = (i: number) => within(rows()[i]).getByRole('checkbox');

describe('Yearly costs worth setting aside (item 3)', () => {
  it('groups the rows, names each with its months and a year, and starts with nothing ticked', async () => {
    stubFetch({ '/api/setasides': LIST });
    renderAt(<SetAsides />, {}, '/spending/setasides');
    const card = await screen.findByTestId('sa-suggestions');
    expect(within(card).getByRole('heading', { name: 'Yearly costs worth setting aside' })).toBeInTheDocument();
    expect(within(card).getByText('A similar amount in the same month each year. Not counted until you set it aside.')).toBeInTheDocument();
    expect([...card.querySelectorAll('.sa-sugg__label')].map((l) => l.textContent)).toEqual(['Home', 'Car', 'Other']);
    expect(rows().map((r) => r.textContent?.replace(/Change first · Not this one$/, ''))).toEqual([
      'Home insuranceJul · $1,800 a year', 'DMV registrationMar · $412 a year', 'Maple Court HOAJan, Jul · $900 a year']);
    expect(screen.getAllByRole('checkbox').every((b) => !(b as HTMLInputElement).checked)).toBe(true);
    expect(screen.queryByRole('region', { name: /picked/ })).toBeNull();
    expect(screen.queryByText(/Set all/)).toBeNull();
    expect(within(rows()[0]).getByRole('link', { name: 'Change first: Home insurance' })).toHaveAttribute('href',
      '/b/ours/spending/setasides/new?name=Home+insurance&kind=yearly&amount=180000&due_month=7&due_day=1&payee_key=STATE+FARM&category=insurance');
  });

  it('a click ticks a row, Shift-click ticks the range, and the bar adds up the months', async () => {
    stubFetch({ '/api/setasides': LIST });
    renderAt(<SetAsides />, {}, '/spending/setasides');
    await screen.findByTestId('sa-suggestions');
    fireEvent.click(box(0));
    expect(screen.getByRole('region', { name: '1 picked · $150 a month' })).toBeInTheDocument();
    fireEvent.click(box(2), { shiftKey: true });
    expect([0, 1, 2].map((i) => (box(i) as HTMLInputElement).checked)).toEqual([true, true, true]);
    expect(screen.getByRole('region', { name: '3 picked · $259 a month' })).toBeInTheDocument();
    fireEvent.click(rows()[1]);                                         // the row itself toggles too
    expect(screen.getByRole('region', { name: '2 picked · $225 a month' })).toBeInTheDocument();
  });

  it('Set aside makes them in one write; they fold away, the toast says so, and Undo brings them back', async () => {
    let list: SetAsideList = LIST;
    const fetchMock = stubFetch({
      '/api/setasides': () => reply(list),
      'POST /api/setasides/many': () => { list = { ...LIST, suggestions: LIST.suggestions.slice(2) }; return reply({ ids: [41, 42], monthly_cents: 18_433, undo: 'tok-m' }, 201); },
      'POST /api/undo/tok-m': () => { list = LIST; return reply({ undone: 0, transaction: null }); },
    });
    renderAt(<SetAsides />, {}, '/spending/setasides');
    await screen.findByTestId('sa-suggestions');
    fireEvent.click(box(0));
    fireEvent.click(box(1));
    fireEvent.click(within(screen.getByRole('region', { name: '2 picked · $184 a month' })).getByRole('button', { name: 'Set aside' }));
    expect(await screen.findByRole('status')).toHaveTextContent('Set aside 2 · $184 a month · Undo');
    const sent = callsTo(fetchMock, 'POST', '/api/setasides/many');
    expect(sent).toHaveLength(1);
    expect((sent[0].body as { items: { name: string; kind: string; amount_cents: number; payee_key: string }[] }).items.map((i) => [i.name, i.kind, i.amount_cents, i.payee_key])).toEqual([
      ['Home insurance', 'yearly', 180_000, 'STATE FARM'], ['DMV registration', 'yearly', 41_200, 'ST OF CA DMV INTERNET']]);
    await waitFor(() => expect(rows()).toHaveLength(1));
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Undo' })); });
    await waitFor(() => expect(rows()).toHaveLength(3));
    expect(callsTo(fetchMock, 'POST', '/api/undo/tok-m')).toHaveLength(1);
  });

  it("a refusal shows the server's words under the bar, keeps the ticks, and makes nothing", async () => {
    stubFetch({ '/api/setasides': LIST, 'POST /api/setasides/many': () => reply({ error: 'Choose a month from 1 to 12.' }, 422) });
    renderAt(<SetAsides />, {}, '/spending/setasides');
    await screen.findByTestId('sa-suggestions');
    fireEvent.click(box(0));
    fireEvent.click(screen.getByRole('button', { name: 'Set aside' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Choose a month from 1 to 12.');
    expect((box(0) as HTMLInputElement).checked).toBe(true);
    expect(screen.queryByRole('status')).toBeNull();
  });

  it('Not this one dismisses the row, as before', async () => {
    const fetchMock = stubFetch({ '/api/setasides': LIST, 'POST /api/setasides/suggestions/dismiss': { ...LIST, suggestions: LIST.suggestions.slice(1) } });
    renderAt(<SetAsides />, {}, '/spending/setasides');
    await screen.findByTestId('sa-suggestions');
    fireEvent.click(within(rows()[0]).getByRole('button', { name: 'Not this one: Home insurance' }));
    await waitFor(() => expect(callsTo(fetchMock, 'POST', '/api/setasides/suggestions/dismiss')).toHaveLength(1));
    expect(callsTo(fetchMock, 'POST', '/api/setasides/suggestions/dismiss')[0].body).toEqual({ payee_key: 'STATE FARM', category: 'insurance' });
  });

  it('a viewer sees the rows with no checkboxes and nothing to press', async () => {
    stubFetch({ '/api/setasides': LIST });
    renderAt(<SetAsides />, { role: 'viewer' }, '/spending/setasides');
    await screen.findByTestId('sa-suggestions');
    expect(rows()).toHaveLength(3);
    expect(screen.queryAllByRole('checkbox')).toHaveLength(0);
    expect(screen.queryByText('Change first')).toBeNull();
    expect(screen.getByText('Not counted until a manager sets them aside.')).toBeInTheDocument();
  });
});
