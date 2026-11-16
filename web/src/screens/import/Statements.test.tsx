import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { letTestingLibraryDriveFakeTimers, useFakeTimers } from '../../test-clock';
import { callsTo, reply, renderAt, stubFetch } from '../../test-utils';
import { statementLine } from './fixtures';
import Statements from './Statements';

beforeEach(() => { useFakeTimers(); letTestingLibraryDriveFakeTimers(); });
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

const FACTS = { kind: 'card', institution: 'Summit Card Services', label: null, last4: '4417', period: ['2026-03-01', '2026-03-31'],
  opening_cents: 120410, closing_cents: 231855, opening_label: 'Previous Balance', closing_label: 'New Balance' };
const DETAIL = (state: string, gap = 0) => ({
  id: 41, state, gap_cents: gap, anyway: false, pages: 2, statement: FACTS, unreadable: [],
  sections: [{ title: 'Payments and credits', rows: 1, sum_cents: 120410, total_cents: null },
             { title: 'Purchases', rows: 2, sum_cents: -10538, total_cents: gap ? -11778 : -10538 }],
  rows: [{ i: 0, date: '2026-03-18', description: 'AUTOMATIC PAYMENT - THANK YOU', amount_cents: 120410, page: 1, section: 'Payments and credits', state: 'read' },
         { i: 1, date: '2026-03-15', description: "TRADER JOE'S #552", amount_cents: -6418, page: 1, section: 'Purchases', state: 'read' },
         { i: 2, date: '2026-03-16', description: 'SHELL OIL 5744', amount_cents: -4120, page: 2, section: 'Purchases', state: 'read' }],
});

describe('the layout check', () => {
  it('shows the balance line, sections with counts and the rows as printed, and Looks right', async () => {
    const fn = stubFetch({ '/api/import/statements/41': DETAIL('layout'), 'POST /api/import/statements/41/layout': { statement: statementLine() },
      '/api/import/statements': { statements: [], gateway: 'answering' } });
    const onDone = vi.fn();
    renderAt(<Statements line={statementLine({ state: 'layout' })} onDone={onDone} />, {}, '/settings/import');
    expect(await screen.findByRole('region', { name: 'Statement_0324.pdf: check the layout' })).toBeInTheDocument();
    expect(screen.getByText('Previous Balance $1,204.10 → New Balance $2,318.55 · adds up ✓')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Purchases 2 rows', level: 4 })).toBeInTheDocument();
    expect(screen.getByText('64.18')).toBeInTheDocument();                         // a card's purchase, as printed
    expect(screen.getByText('-1,204.10')).toBeInTheDocument();
    expect(screen.getByText('Steward remembers this layout.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Looks right' }));
    await waitFor(() => expect(onDone).toHaveBeenCalledWith('ready'));
    expect(callsTo(fn, 'POST', '/api/import/statements/41/layout')[0].body).toEqual({ answer: 'right' });
  });

  it('Not right asks again and hands on to row review, saying which state the line is in', async () => {
    const fn = stubFetch({ '/api/import/statements/41': DETAIL('layout'),
      'POST /api/import/statements/41/layout': { statement: statementLine({ state: 'off', gap_cents: -1240 }) },
      '/api/import/statements': { statements: [], gateway: 'answering' } });
    const onDone = vi.fn();
    renderAt(<Statements line={statementLine({ state: 'layout' })} onDone={onDone} />, {}, '/settings/import');
    fireEvent.click(await screen.findByRole('button', { name: 'Not right' }));
    await waitFor(() => expect(callsTo(fn, 'POST', '/api/import/statements/41/layout')[0].body).toEqual({ answer: 'wrong' }));
    expect(onDone).not.toHaveBeenCalled();                                         // the line itself stays open, now in row review
  });
});

describe('row review', () => {
  it('counts the gap down after an edit, names the off section, and Done makes it ready', async () => {
    const fn = stubFetch({
      '/api/import/statements/41': DETAIL('off', -1240),
      '/api/import/statements': { statements: [], gateway: 'answering' },
      'POST /api/import/statements/41/rows': (_u, init) => {
        const body = JSON.parse(String(init.body)) as { ops: unknown[]; done?: boolean };
        return reply({ state: body.done ? 'ready' : 'off', gap_cents: 0, sections: DETAIL('off', 0).sections, rows: DETAIL('off').rows });
      },
    });
    const onDone = vi.fn();
    renderAt(<Statements line={statementLine({ state: 'off', gap_cents: -1240 })} onDone={onDone} />, {}, '/settings/import');
    const gap = await screen.findByText(/^Off by \$12\.40/);
    expect(gap).toHaveTextContent('Off by $12.40 · Purchases are off by $12.40');
    expect(gap).toHaveAttribute('aria-live', 'polite');
    const amount = screen.getByLabelText('Amount, row 2');
    fireEvent.change(amount, { target: { value: '76.58' } });
    fireEvent.blur(amount);
    expect(await screen.findByText('Adds up ✓')).toBeInTheDocument();
    expect(callsTo(fn, 'POST', '/api/import/statements/41/rows')[0].body).toEqual({ ops: [{ op: 'edit', i: 1, amount_cents: -7658 }] });
    expect(screen.queryByLabelText('Import anyway')).toBeNull();                   // only while off
    fireEvent.click(screen.getByRole('button', { name: 'Done' }));
    await waitFor(() => expect(onDone).toHaveBeenCalledWith('ready'));
  });

  it('puts focus on the gap line when it opens', async () => {
    stubFetch({ '/api/import/statements/41': DETAIL('off', -1240), '/api/import/statements': { statements: [], gateway: 'answering' } });
    renderAt(<Statements line={statementLine({ state: 'off', gap_cents: -1240 })} onDone={vi.fn()} />, {}, '/settings/import');
    const gap = await screen.findByText(/^Off by \$12\.40/);
    await waitFor(() => expect(gap).toHaveFocus());
  });

  it('Remove collapses the row to Removed · Undo, with focus on Undo', async () => {
    stubFetch({
      '/api/import/statements/41': DETAIL('off', -1240),
      'POST /api/import/statements/41/rows': (_u, init) => {
        const op = (JSON.parse(String(init.body)) as { ops: { op: string }[] }).ops[0].op;
        const rows = DETAIL('off').rows.map((r) => (r.i === 2 ? { ...r, state: op === 'remove' ? 'removed' : 'read' } : r));
        return reply({ state: 'off', gap_cents: op === 'remove' ? 2880 : -1240, sections: DETAIL('off').sections, rows });
      },
    });
    renderAt(<Statements line={statementLine({ state: 'off', gap_cents: -1240 })} onDone={vi.fn()} />, {}, '/settings/import');
    fireEvent.click(await screen.findByRole('button', { name: 'Remove row 3' }));
    const undo = await screen.findByRole('button', { name: 'Removed · Undo' });
    await waitFor(() => expect(undo).toHaveFocus());
    fireEvent.click(undo);
    expect(await screen.findByRole('button', { name: 'Remove row 3' })).toBeInTheDocument();
  });

  it('Import anyway shows while off and says so', async () => {
    const fn = stubFetch({ '/api/import/statements/41': DETAIL('off', -1240), '/api/import/statements': { statements: [], gateway: 'answering' },
      'PATCH /api/import/statements/41': { statement: statementLine({ state: 'off', anyway: true }) } });
    renderAt(<Statements line={statementLine({ state: 'off', gap_cents: -1240 })} onDone={vi.fn()} />, {}, '/settings/import');
    fireEvent.click(await screen.findByLabelText('Import anyway'));
    await act(async () => {});
    expect(callsTo(fn, 'PATCH', '/api/import/statements/41')[0].body).toEqual({ anyway: true });
  });
});

describe('when the detail will not load', () => {
  it('says so instead of opening nothing, and is busy while it loads', async () => {
    stubFetch({ '/api/import/statements/41': () => reply({ error: 'That statement is gone.' }, 404) });
    renderAt(<Statements line={statementLine({ state: 'off', gap_cents: -1240 })} onDone={vi.fn()} />, {}, '/settings/import');
    expect(await screen.findByText('That statement is gone.')).toBeInTheDocument();
    expect(screen.queryByRole('region')).toBeNull();
  });
});

describe('a scan in row review', () => {
  it('marks descriptions read from a scan for checking', async () => {
    const scanned = { ...DETAIL('off', -1240), rows: DETAIL('off').rows.map((r) => ({ ...r, scan: true })) };
    stubFetch({ '/api/import/statements/41': scanned });
    renderAt(<Statements line={statementLine({ state: 'off', gap_cents: -1240, kind: 'scan' })} onDone={vi.fn()} />, {}, '/settings/import');
    expect(await screen.findByText('Descriptions read from a scan · check them')).toBeInTheDocument();
    expect(screen.getByLabelText('Description, row 2')).toHaveClass('imp-st__scan');
    expect(screen.getByLabelText('Description, row 2')).toHaveAccessibleDescription('read from a scan');
  });

  it('a text statement has no note and no marks', async () => {
    stubFetch({ '/api/import/statements/41': DETAIL('off', -1240) });
    renderAt(<Statements line={statementLine({ state: 'off', gap_cents: -1240 })} onDone={vi.fn()} />, {}, '/settings/import');
    await screen.findByLabelText('Description, row 2');
    expect(screen.queryByText('Descriptions read from a scan · check them')).toBeNull();
    expect(screen.getByLabelText('Description, row 2')).not.toHaveClass('imp-st__scan');
  });
});

const IRA = (state: string, gap = 0) => ({
  id: 41, state, gap_cents: gap, anyway: false, pages: 1, unreadable: [], rows: [], sections: [],
  statement: { kind: 'retirement', institution: 'Pinecrest Funds', label: null, last4: '8765', period: ['2026-01-01', '2026-03-31'],
    opening_cents: null, closing_cents: 8421033, total_cents: 8421033, opening_label: 'Beginning balance', closing_label: 'Ending balance' },
  holdings: [
    { i: 0, symbol: 'VTSAX', name: 'Total Stock Market Index Admiral', shares_milli: 412118, value_cents: 5230120, cash: false, page: 1, state: 'read' },
    { i: 1, symbol: 'VMFXX', name: 'Federal Money Market', shares_milli: 0, value_cents: 3190913 - gap, cash: true, page: 1, state: 'read' }],
});

describe('the holdings check', () => {
  it('shows the ending balance, the holdings and the check, with Looks right', async () => {
    const fn = stubFetch({ '/api/import/statements/41': IRA('holdings'), 'POST /api/import/statements/41/layout': { statement: statementLine() },
      '/api/import/statements': { statements: [], gateway: 'answering' } });
    const onDone = vi.fn();
    renderAt(<Statements line={statementLine({ state: 'holdings', statement_kind: 'retirement' })} onDone={onDone} />, {}, '/settings/import');
    expect(await screen.findByText('Ending balance $84,210.33 on Mar 31')).toBeInTheDocument();
    expect(screen.getByText('Total Stock Market Index Admiral')).toBeInTheDocument();
    expect(screen.getByText('Holdings add up to the total ✓')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Looks right' }));
    await waitFor(() => expect(onDone).toHaveBeenCalledWith('ready'));
    expect(callsTo(fn, 'POST', '/api/import/statements/41/layout')[0].body).toEqual({ answer: 'right' });
  });

  it('holdings review counts the gap to the total down', async () => {
    const fn = stubFetch({ '/api/import/statements/41': IRA('off', 25000),
      'POST /api/import/statements/41/holdings': { state: 'off', gap_cents: 0, holdings: IRA('off').holdings } });
    renderAt(<Statements line={statementLine({ state: 'off', statement_kind: 'retirement', gap_cents: 25000 })} onDone={vi.fn()} />, {}, '/settings/import');
    expect(await screen.findByText('Holdings are $250.00 short of the total')).toBeInTheDocument();
    const value = screen.getByLabelText('Value, row 2');
    fireEvent.change(value, { target: { value: '31,909.13' } });
    fireEvent.blur(value);
    expect(await screen.findByText('Holdings add up to the total ✓')).toBeInTheDocument();
    expect(callsTo(fn, 'POST', '/api/import/statements/41/holdings')[0].body).toEqual({ ops: [{ op: 'edit', i: 1, value_cents: 3190913 }] });
  });

  it('holdings review: Remove collapses a holding to Removed · Undo, and Undo restores it', async () => {
    const fn = stubFetch({ '/api/import/statements/41': IRA('off', 25000),
      'POST /api/import/statements/41/holdings': (_u, init) => {
        const op = (JSON.parse(String(init.body)) as { ops: { op: string }[] }).ops[0].op;
        const holdings = IRA('off', 25000).holdings.map((h) => (h.i === 0 ? { ...h, state: op === 'remove' ? 'removed' : 'read' } : h));
        return reply({ state: 'off', gap_cents: op === 'remove' ? 5255120 : 25000, holdings });
      } });
    renderAt(<Statements line={statementLine({ state: 'off', statement_kind: 'retirement', gap_cents: 25000 })} onDone={vi.fn()} />, {}, '/settings/import');
    fireEvent.click(await screen.findByRole('button', { name: 'Remove row 1' }));
    const undo = await screen.findByRole('button', { name: 'Removed · Undo' });
    await waitFor(() => expect(undo).toHaveFocus());
    expect(screen.getByText('Holdings are $52,551.20 short of the total')).toBeInTheDocument();
    fireEvent.click(undo);
    expect(await screen.findByRole('button', { name: 'Remove row 1' })).toBeInTheDocument();
    expect(callsTo(fn, 'POST', '/api/import/statements/41/holdings').map((c) => c.body))
      .toEqual([{ ops: [{ op: 'remove', i: 0 }] }, { ops: [{ op: 'restore', i: 0 }] }]);
  });

  it('holdings review: Add a row reads shares and a value as typed and adds the holding', async () => {
    const added = { i: 2, symbol: 'FXAIX', name: '500 Index', shares_milli: 1250500, value_cents: 1234567, cash: false, page: null, state: 'added' };
    const fn = stubFetch({ '/api/import/statements/41': IRA('off', 25000),
      'POST /api/import/statements/41/holdings': { state: 'off', gap_cents: -1209567, holdings: [...IRA('off', 25000).holdings, added] } });
    renderAt(<Statements line={statementLine({ state: 'off', statement_kind: 'retirement', gap_cents: 25000 })} onDone={vi.fn()} />, {}, '/settings/import');
    fireEvent.click(await screen.findByRole('button', { name: 'Add a row' }));
    fireEvent.change(screen.getByLabelText('Symbol, row 3'), { target: { value: ' FXAIX ' } });
    fireEvent.change(screen.getByLabelText('Name, row 3'), { target: { value: '500 Index' } });
    fireEvent.change(screen.getByLabelText('Shares, row 3'), { target: { value: '1,250.5' } });
    const value = screen.getByLabelText('Value, row 3');
    fireEvent.change(value, { target: { value: '$12,345.67' } });
    fireEvent.blur(value);
    expect(await screen.findByText('Holdings are $12,095.67 over the total')).toBeInTheDocument();
    expect(callsTo(fn, 'POST', '/api/import/statements/41/holdings').map((c) => c.body))
      .toEqual([{ ops: [{ op: 'add', symbol: 'FXAIX', name: '500 Index', shares_milli: 1250500, value_cents: 1234567 }] }]);
    expect(screen.getByRole('button', { name: 'Add a row' })).toBeEnabled();      // the draft row became the added holding
    expect(screen.getByLabelText('Value, row 3')).toHaveValue('12,345.67');
  });

  it('holdings review: Import anyway shows while off and is sent as anyway', async () => {
    const fn = stubFetch({ '/api/import/statements/41': IRA('off', 25000), '/api/import/statements': { statements: [], gateway: 'answering' },
      'PATCH /api/import/statements/41': { statement: statementLine({ state: 'off', statement_kind: 'retirement', anyway: true }) } });
    renderAt(<Statements line={statementLine({ state: 'off', statement_kind: 'retirement', gap_cents: 25000 })} onDone={vi.fn()} />, {}, '/settings/import');
    const box = await screen.findByLabelText('Import anyway');
    fireEvent.click(box);
    await act(async () => {});
    expect(callsTo(fn, 'PATCH', '/api/import/statements/41').map((c) => c.body)).toEqual([{ anyway: true }]);
    expect(box).toBeChecked();
  });

  it('holdings review: Done sends no ops with done and hands back the new state', async () => {
    const fn = stubFetch({ '/api/import/statements/41': IRA('off', 0), '/api/import/statements': { statements: [], gateway: 'answering' },
      'POST /api/import/statements/41/holdings': { state: 'ready', gap_cents: 0, holdings: IRA('off').holdings } });
    const onDone = vi.fn();
    renderAt(<Statements line={statementLine({ state: 'off', statement_kind: 'retirement', gap_cents: 0 })} onDone={onDone} />, {}, '/settings/import');
    expect(await screen.findByText('Holdings add up to the total ✓')).toBeInTheDocument();
    expect(screen.queryByLabelText('Import anyway')).toBeNull();                   // only while off by something
    fireEvent.click(screen.getByRole('button', { name: 'Done' }));
    await waitFor(() => expect(onDone).toHaveBeenCalledWith('ready'));
    expect(callsTo(fn, 'POST', '/api/import/statements/41/holdings').map((c) => c.body)).toEqual([{ ops: [], done: true }]);
  });

  it('a loan’s layout check shows its principal', async () => {
    stubFetch({ '/api/import/statements/41': { ...IRA('layout'), holdings: [], statement: { ...IRA('layout').statement, kind: 'loan',
      closing_cents: 841207, total_cents: null, closing_label: 'Principal Balance' } } });
    renderAt(<Statements line={statementLine({ state: 'layout', statement_kind: 'loan' })} onDone={vi.fn()} />, {}, '/settings/import');
    expect(await screen.findByText('Principal Balance $8,412.07')).toBeInTheDocument();
  });

  it('an empty holdings review says Check holdings, with no update note when the gateway reads holdings', async () => {
    stubFetch({ '/api/import/statements/41': { ...IRA('off'), gap_cents: null, holdings: [], holdings_update: false } });
    renderAt(<Statements line={statementLine({ state: 'off', statement_kind: 'retirement', gap_cents: null })} onDone={vi.fn()} />, {}, '/settings/import');
    expect(await screen.findByText('Check holdings')).toBeInTheDocument();
    expect(screen.queryByText('Check rows')).toBeNull();
    expect(screen.queryByText('The gateway needs an update to read holdings.')).toBeNull();
  });

  it('a scan read for rows because the gateway lacks holdings says it needs an update', async () => {
    stubFetch({ '/api/import/statements/41': { ...IRA('off'), gap_cents: null, holdings: [], holdings_update: true } });
    renderAt(<Statements line={statementLine({ state: 'off', statement_kind: 'retirement', gap_cents: null })} onDone={vi.fn()} />, {}, '/settings/import');
    expect(await screen.findByText('The gateway needs an update to read holdings.')).toHaveClass('small', 'muted');
  });
});
