import { fireEvent, render, screen } from '@testing-library/react';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { Confirm } from './Confirm';
import { ACCT_BANK, ACCT_CARD, row, staged } from './fixtures';
import type { Answers, Row } from './logic';
import type { Account } from '../../api/types';

function Host({ start, account, onUse = () => {} }: { start: Row; account: Account | null; onUse?: () => void }) {
  const [r, setR] = useState(start);
  return <Confirm row={r} account={account} onChange={(answers: Answers) => setR({ ...r, answers })} onUse={onUse} />;
}

describe('the column confirm', () => {
  it('pre-sets the guessed columns, and choosing a field elsewhere moves it', () => {
    render(<Host start={row(staged())} account={ACCT_CARD} />);
    expect(screen.getByRole('table', { name: /^Columns in activity/ })).toBeInTheDocument();
    const amount = screen.getByLabelText('Column 3: Amount') as HTMLSelectElement;
    expect(amount.value).toBe('amount');
    fireEvent.change(screen.getByLabelText('Column 4: Type'), { target: { value: 'amount' } });
    expect(amount.value).toBe('ignore');
    expect(screen.queryByText('Choose an amount column, or both a money-out and a money-in column.')).toBeNull();
  });

  it('says what a valid layout needs', () => {
    render(<Host start={row(staged())} account={ACCT_CARD} />);
    fireEvent.change(screen.getByLabelText('Column 3: Amount'), { target: { value: 'ignore' } });
    expect(screen.getByText('Choose an amount column, or both a money-out and a money-in column.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Use this layout' })).toBeDisabled();
  });

  it('pre-selects a clear sign for a card in its words', () => {
    render(<Host start={row(staged())} account={ACCT_CARD} />);
    const q = screen.getByRole('group', { name: 'Purchases look positive in this file. Which way do the signs run?' });
    expect(q).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: 'Purchases are positive' })).toBeChecked();
    expect(screen.getByRole('button', { name: 'Use this layout' })).toBeEnabled();
  });

  it('leaves an ambiguous bank question unanswered until it’s answered', () => {
    const onUse = vi.fn();
    render(<Host start={row(staged())} account={ACCT_BANK} onUse={onUse} />);
    screen.getByRole('group', { name: 'Money out looks positive in this file. Which way do the signs run?' });
    expect(screen.getByRole('radio', { name: 'Money out is positive' })).not.toBeChecked();
    expect(screen.getByRole('radio', { name: 'Money out is negative' })).not.toBeChecked();
    expect(screen.getByRole('button', { name: 'Use this layout' })).toBeDisabled();
    fireEvent.click(screen.getByRole('radio', { name: 'Money out is negative' }));
    fireEvent.click(screen.getByRole('button', { name: 'Use this layout' }));
    expect(onUse).toHaveBeenCalledOnce();
  });

  it('asks for an account before the sign', () => {
    render(<Host start={row(staged())} account={null} />);
    expect(screen.getByRole('group', { name: 'Choose an account' })).toBeInTheDocument();
    expect(screen.queryByRole('radio')).toBeNull();
  });

  it('asks the date with options from the file’s own example, and says how dates read', () => {
    render(<Host start={row(staged({ dateQuestion: true }))} account={ACCT_CARD} />);
    screen.getByRole('group', { name: 'Is 03/04/2024 March 4 or April 3?' });
    expect(screen.queryByText(/^Dates read as/)).toBeNull();
    fireEvent.click(screen.getByRole('radio', { name: 'April 3' }));
    expect(screen.getByText('Dates read as day/month/year.')).toBeInTheDocument();
    expect(screen.getByText('Steward remembers this layout, so the next file like it asks nothing.')).toBeInTheDocument();
  });

  it('a remembered layout the evidence contradicts asks again', () => {
    const f = staged({ state: 'remembered', negate: false });
    render(<Host start={{ ...row(f), answers: { ...row(f).answers!, negate: null } }} account={ACCT_CARD} />);
    expect(screen.getByText("This file's signs look the other way from last time.")).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: 'Purchases are positive' })).not.toBeChecked();
    expect(screen.queryByRole('table')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Use this layout' })).toBeNull();
  });
});
