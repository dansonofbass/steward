import { fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { letTestingLibraryDriveFakeTimers, useFakeTimers } from '../../test-clock';
import { callsTo, reply, renderAt, stubFetch } from '../../test-utils';
import { ACCT_BANK, ACCT_CARD, ACCT_IRA, ACCT_MANUAL, statementLine } from './fixtures';
import { setGatewayName } from '../../lib/gatewayName';
import { StatementRow } from './StatementRow';

beforeEach(() => { useFakeTimers(); letTestingLibraryDriveFakeTimers(); });
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

describe('a statement line', () => {
  it('shows its name, its words, its account and ×, and a line that needs a look opens', () => {
    stubFetch({});
    const onOpen = vi.fn();
    const onAccount = vi.fn();
    renderAt(<ul><StatementRow line={statementLine({ state: 'layout' })} gateway="answering" accounts={[ACCT_CARD, ACCT_BANK]}
      open={false} onOpen={onOpen} onAccount={onAccount} onRemove={vi.fn()} /></ul>, {}, '/settings/import');
    fireEvent.click(screen.getByRole('button', { name: 'Check the layout · 1 look' }));
    expect(onOpen).toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText('Account for Statement_0324.pdf'), { target: { value: String(ACCT_CARD.id) } });
    expect(onAccount).toHaveBeenCalledWith(String(ACCT_CARD.id));
    expect(screen.getByRole('button', { name: 'Remove Statement_0324.pdf' })).toBeInTheDocument();
  });

  it('a scan with no account shows the prompt and no gap, then the check once the account is chosen', () => {
    stubFetch({});
    const props = { gateway: 'answering' as const, accounts: [ACCT_CARD, ACCT_BANK], open: false, onOpen: vi.fn(), onAccount: vi.fn(), onRemove: vi.fn() };
    const none = statementLine({ kind: 'scan', state: 'ready', account_id: null, needs_account: true, gap_cents: null });
    const show = (line: ReturnType<typeof statementLine>) => renderAt(<ul><StatementRow line={line} {...props} /></ul>, {}, '/settings/import');
    const first = show(none);
    expect(screen.getByText('Choose its account to check it')).toBeInTheDocument();
    expect(screen.queryByText(/Off by/)).toBeNull();
    expect(screen.queryByRole('button', { name: /Check rows|Choose its account/ })).toBeNull();
    first.unmount();
    const second = show({ ...none, account_id: ACCT_CARD.id, needs_account: false });
    expect(screen.getByText(/adds up ✓/)).toBeInTheDocument();
    second.unmount();
    show({ ...none, state: 'off', account_id: ACCT_BANK.id, needs_account: false, gap_cents: 689700 });
    expect(screen.getByRole('button', { name: 'Off by $6,897.00 · Check rows' })).toBeInTheDocument();
  });

  it('an error is words in warn ink with no account to pick', () => {
    stubFetch({});
    renderAt(<ul><StatementRow line={statementLine({ state: 'error', error: 'too_slow', error_text: 'This PDF took too long to read.' })}
      gateway="answering" accounts={[ACCT_CARD]} open={false} onOpen={vi.fn()} onAccount={vi.fn()} onRemove={vi.fn()} /></ul>, {},
    '/settings/import');
    expect(screen.getByText('This PDF took too long to read.')).toHaveClass('imp-row__tag--warn');
    expect(screen.queryByLabelText('Account for Statement_0324.pdf')).toBeNull();
  });

  it('a page that failed offers Try again as a button', async () => {
    const fn = stubFetch({ 'POST /api/import/statements/41/retry': { statement: statementLine({ state: 'queued' }) } });
    renderAt(<ul><StatementRow line={statementLine({ state: 'error', error: 'page_failed', error_text: "The gateway couldn't read page 3 · Try again" })}
      gateway="answering" accounts={[ACCT_CARD]} open={false} onOpen={vi.fn()} onAccount={vi.fn()} onRemove={vi.fn()} /></ul>, {}, '/settings/import');
    expect(screen.getByText(/couldn't read page 3/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    await waitFor(() => expect(callsTo(fn, 'POST', '/api/import/statements/41/retry')).toHaveLength(1));
  });

  it('keeps the other suffixes after Try again, and shows a refused retry', async () => {
    stubFetch({ 'POST /api/import/statements/41/retry': () => reply({ error: 'That statement changed.' }, 409) });
    renderAt(<ul><StatementRow line={statementLine({ state: 'error', error: 'layout_failed', added_by: 'Jane',
      error_text: "The gateway couldn't read this layout · Try again" })}
      gateway="answering" accounts={[ACCT_CARD]} open={false} onOpen={vi.fn()} onAccount={vi.fn()} onRemove={vi.fn()} /></ul>, {}, '/settings/import');
    expect(screen.getByText(/Added by Jane/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByText('That statement changed.')).toBeInTheDocument();
  });

  it('restarted has no Try again', () => {
    stubFetch({});
    renderAt(<ul><StatementRow line={statementLine({ state: 'error', error: 'restarted', error_text: 'Steward restarted on page 7 of 12. Add the file again to finish.' })}
      gateway="answering" accounts={[ACCT_CARD]} open={false} onOpen={vi.fn()} onAccount={vi.fn()} onRemove={vi.fn()} /></ul>, {}, '/settings/import');
    expect(screen.queryByRole('button', { name: 'Try again' })).toBeNull();
  });

  it('a holdings or loan statement on an account of another type gets a gentle note, and the line still works', () => {
    stubFetch({});
    const props = { gateway: 'answering' as const, accounts: [ACCT_CARD, ACCT_BANK, ACCT_MANUAL, ACCT_IRA], open: false, onOpen: vi.fn(),
      onAccount: vi.fn(), onRemove: vi.fn() };
    const show = (p: Partial<ReturnType<typeof statementLine>>) =>
      renderAt(<ul><StatementRow line={statementLine({ holdings: 3, rows: 0, ...p })} {...props} /></ul>, {}, '/settings/import');
    let view = show({ statement_kind: 'investment', account_id: ACCT_MANUAL.id });
    expect(screen.getByText("Cash box isn't an investment account. Holdings usually go on one.")).toHaveClass('small', 'muted');
    expect(screen.getByLabelText('Account for Statement_0324.pdf')).toBeEnabled();
    view.unmount();
    view = show({ statement_kind: 'retirement', account_id: ACCT_IRA.id });
    expect(screen.queryByText(/isn't an/)).toBeNull();
    view.unmount();
    view = show({ statement_kind: 'loan', holdings: null, account_id: ACCT_BANK.id });
    expect(screen.getByText("Mom’s savings isn't a loan account. Loan statements usually go on one.")).toBeInTheDocument();
    view.unmount();
    view = show({ statement_kind: 'investment', account_id: null });
    expect(screen.queryByText(/isn't an/)).toBeNull();
    view.unmount();
    show({ statement_kind: 'card', holdings: null, account_id: ACCT_BANK.id });
    expect(screen.queryByText(/isn't a/)).toBeNull();
  });
  it("keeps the gateway's name in one piece, as typed and capitalized at a sentence start", () => {
    stubFetch({});
    const props = { gateway: 'waiting' as const, accounts: [ACCT_CARD], open: false, onOpen: vi.fn(), onAccount: vi.fn(), onRemove: vi.fn() };
    const show = (line: ReturnType<typeof statementLine>) => renderAt(<ul><StatementRow line={line} {...props} /></ul>, {}, '/settings/import');
    setGatewayName('Zebra-Box');
    let view = show(statementLine({ state: 'waiting' }));
    expect(screen.getByText('Zebra-Box', { selector: '.imp-row__nb' })).toBeInTheDocument();
    view.unmount();
    view = show(statementLine({ state: 'error', error: 'restarted', error_text: 'Zebra-Box was asleep.' }));
    expect(screen.getByText('Zebra-Box', { selector: '.imp-row__nb' })).toBeInTheDocument();
    view.unmount();
    setGatewayName(null);                                        // "the gateway": lower in the middle, capital at the start
    view = show(statementLine({ state: 'waiting' }));
    expect(screen.getByText('the gateway', { selector: '.imp-row__nb' })).toBeInTheDocument();
    view.unmount();
    show(statementLine({ state: 'error', error: 'restarted', error_text: "The gateway couldn't answer." }));
    expect(screen.getByText('The gateway', { selector: '.imp-row__nb' })).toBeInTheDocument();
  });
});
