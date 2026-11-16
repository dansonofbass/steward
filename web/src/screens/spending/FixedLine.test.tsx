import { act, fireEvent, screen } from '@testing-library/react';
import { useState } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { FixedRow } from '../../api/types';
import { callsTo, renderAt, reply, stubFetch } from '../../test-utils';
import { FixedLine } from './FixedLine';
import { OCT } from './fixtures';
import { fixedAmount, fixedText } from './model';

afterEach(() => vi.unstubAllGlobals());
const base: FixedRow = { category: 'utilities', kind: 'fixed', expected: true, expected_cents: 45_000, usual_cents: 45_000, spent_cents: 0,
  refunds_cents: 0, state: 'waiting', tone: 'ring', came_out_on: null, merchant: null, typical_day: 15, new_payee: null };

describe("fixed costs' words (JR's cases table)", () => {
  it.each([
    ['fixed', 'waiting', 0, 'Usually around the 15th'],
    ['commitment', 'waiting', 0, 'Usually around the 15th'],
    ['fixed', 'late', 0, 'Not seen yet · usually by the 15th'],
    ['commitment', 'late', 0, 'Not seen yet · usually by the 15th'],
    ['fixed', 'so_far', 32_800, '$328 so far · usually $450'],
    ['commitment', 'so_far', 1_500, '$15 so far · usually $450'],
    ['fixed', 'under', 32_800, '$328 · usually $450'],
    ['commitment', 'under', 1_500, '$15 · usually $450'],
    ['fixed', 'over', 54_000, '$90 more than usual'],
    ['commitment', 'over', 54_000, '$540 · usually $450'],
    ['fixed', 'none', 0, 'Nothing came out'],
    ['commitment', 'none', 0, 'Nothing came out'],
  ] as const)('%s, %s', (kind, state, spent, text) => {
    expect(fixedText({ ...base, kind, state, spent_cents: spent })).toBe(text);
  });
  it('paid as usual names the payee and the day, and a new payee joins it', () => {
    const paid = { ...base, state: 'as_usual' as const, tone: 'check' as const, spent_cents: 45_000, came_out_on: '2026-10-12', merchant: 'City Power' };
    expect(fixedText(paid)).toBe('City Power · came out Oct 12');
    expect(fixedText({ ...paid, merchant: null })).toBe('Came out Oct 12');
    expect(fixedText({ ...paid, new_payee: { name: 'StreamBox', cents: 799 } })).toBe('City Power · came out Oct 12 · New this month · StreamBox $7.99');
    expect(fixedText({ ...base, typical_day: null })).toBe('Not seen yet');
  });
  it('shows what came out, or what is expected while waiting or late, and nothing when nothing came out', () => {
    expect(fixedAmount(base)).toBe(45_000);
    expect(fixedAmount({ ...base, state: 'late' })).toBe(45_000);
    expect(fixedAmount({ ...base, state: 'so_far', spent_cents: 32_800 })).toBe(32_800);
    expect(fixedAmount({ ...base, state: 'none' })).toBeNull();
  });
});

describe('a fixed cost row', () => {
  const at = (r: FixedRow, canEdit = true) => renderAt(<FixedLine r={r} m={OCT} canEdit={canEdit} />, {}, '/spending');
  it('a check in neutral ink means paid, never green', () => {
    at({ ...base, state: 'as_usual', tone: 'check', spent_cents: 45_000, came_out_on: '2026-10-12', merchant: 'City Power' });
    const row = screen.getByTestId('fixed-row');
    expect(row).toHaveClass('is-check');
    expect(row).toHaveTextContent('City Power · came out Oct 12$450');
    expect(row.querySelector('.money--in')).toBeNull();
    expect(screen.getByRole('link', { name: 'Utilities' })).toHaveAttribute('href', '/b/ours/spending/utilities?month=2026-10');
  });
  it('a bill over usual is amber with See charges; a commitment over usual stays neutral with no link', () => {
    const { unmount } = at({ ...base, state: 'over', tone: 'amber', spent_cents: 54_000 });
    expect(screen.getByTestId('fixed-row')).toHaveClass('is-amber');
    expect(screen.getByRole('link', { name: 'See charges' })).toHaveAttribute('href', '/b/ours/transactions?category=utilities&dates=custom&from=2026-10-01&to=2026-10-25');
    unmount();
    at({ ...base, category: 'giving', kind: 'commitment', state: 'over', tone: 'check', spent_cents: 54_000, outside_cents: 0 });
    expect(screen.getByTestId('fixed-row')).not.toHaveClass('is-amber');
    expect(screen.getByTestId('fixed-row')).toHaveTextContent('$540 · usually $450');
    expect(screen.queryByRole('link', { name: 'See charges' })).toBeNull();
  });
  it('a closed month with nothing paid has no icon and no amount', () => {
    at({ ...base, state: 'none', tone: 'quiet' });
    const row = screen.getByTestId('fixed-row');
    expect(row.querySelector('svg.i:not(.sp-fixed__chev)')).toBeNull();
    expect(row).toHaveTextContent(/^UtilitiesNothing came out$/);
  });
});

describe('Giving outside these accounts', () => {
  const giving: FixedRow = { ...base, category: 'giving', kind: 'commitment', state: 'as_usual', tone: 'check', spent_cents: 20_000,
    usual_cents: 20_000, came_out_on: '2026-10-03', merchant: 'Grace Community', outside_cents: 0 };
  it('a manager adds it, the row says it, and Undo takes it back', async () => {
    let outside = 0;
    const fetchMock = stubFetch({
      'POST /api/facts': (_u, init) => { outside = Number(JSON.parse(String(init.body)).value); return reply({ key: 'giving.outside_cents', value: String(outside), as_of: '2026-10-25', note: null, undo: 'tok-1' }, 201); },
      'POST /api/undo/tok-1': () => { outside = 0; return reply({ undone: 0, transaction: null }); },
    });
    // The page refetches after a save; here the saved figure is handed down by hand.
    let show: (cents: number) => void = () => {};
    function Row() {
      const [cents, setCents] = useState(0);
      show = setCents;
      return <FixedLine r={{ ...giving, outside_cents: cents }} m={OCT} canEdit />;
    }
    renderAt(<Row />, {}, '/spending');
    fireEvent.click(screen.getByRole('button', { name: 'Add it' }));
    fireEvent.change(screen.getByRole('textbox', { name: 'A month, outside these accounts' }), { target: { value: '50' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(await screen.findByRole('status')).toHaveTextContent('Saved · Undo');
    expect(callsTo(fetchMock, 'POST', '/api/facts')[0].body).toEqual({ key: 'giving.outside_cents', value: '5000' });
    act(() => show(outside));
    expect(screen.getByTestId('fixed-row')).toHaveTextContent('plus $50 a month outside these accounts');
    expect(screen.getByRole('button', { name: 'Change giving outside these accounts' })).toBeInTheDocument();
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Undo' })); });
    expect(callsTo(fetchMock, 'POST', '/api/undo/tok-1')).toHaveLength(1);
  });
  it('a viewer sees the phrase but no prompt and no pencil', () => {
    renderAt(<FixedLine r={{ ...giving, outside_cents: 5_000 }} m={OCT} canEdit={false} />, { role: 'viewer' }, '/spending');
    expect(screen.getByTestId('fixed-row')).toHaveTextContent('plus $50 a month outside these accounts');
    expect(screen.queryByRole('button')).toBeNull();
    renderAt(<FixedLine r={giving} m={OCT} canEdit={false} />, { role: 'viewer' }, '/spending');
    expect(screen.queryByText(/Giving outside these accounts\?/)).toBeNull();
  });
});
