import { fireEvent, render, screen, within } from '@testing-library/react';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { PREVIEW } from './fixtures';
import { Look, type LookLine } from './Look';
import { Preview } from './Preview';

const lines = () => [...document.querySelectorAll('dl.imp-pv > div')].map((d) => d.textContent);

describe('the preview', () => {
  it('lists every line and its value, and Import N', () => {
    render(<Preview reply={PREVIEW} changed={false} busy={false} onImport={() => {}} onBack={() => {}} onLook={() => {}} />);
    expect(lines()).toEqual([
      'New transactions2,486', 'Already in Steward (skipped)318 · Look', 'SimpleFIN already has these (after Aug 4)92 · skipped · Look',
      'Looks the same, check6 · Look', 'CoversNov 2022 – Aug 2024']);
    expect(screen.getByText('activity (3).csv · Row 12: the date "13/45/2024" isn\'t a date.')).toBeInTheDocument();
    expect(screen.getByText('activity (3).csv · 2 balance lines left out')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Import 2,486' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Back' })).toBeInTheDocument();
  });

  it('drops the SimpleFIN date for two accounts, and shows one month alone', () => {
    const two = { ...PREVIEW, simplefin: { n: 92, since: null }, from: '2024-08-01', to: '2024-08-30' };
    render(<Preview reply={two} changed={false} busy={false} onImport={() => {}} onBack={() => {}} onLook={() => {}} />);
    expect(lines()).toContain('SimpleFIN already has these92 · skipped · Look');
    expect(lines()).toContain('CoversAug 2024');
  });

  it('says when something changed, and each Look names its line', () => {
    const onLook = vi.fn();
    render(<Preview reply={PREVIEW} changed busy={false} onImport={() => {}} onBack={() => {}} onLook={onLook} />);
    expect(screen.getByText('Something changed since the preview. Check the new numbers.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Look: Looks the same, check' }));
    fireEvent.click(screen.getByRole('button', { name: 'Look: Already in Steward (skipped)' }));
    expect(onLook.mock.calls).toEqual([['same'], ['already']]);
  });
});

describe('the preview, balances', () => {
  const BAL = { ...PREVIEW, balances: { n: 1, kept: 1, rows: [{ account: 'Amex Gold', as_of: '2026-03-31', cents: -123456, kept: true }] } };

  it('lists the balances with how many were kept, the kept note, and a Look at each row', () => {
    render(<Preview reply={BAL} changed={false} busy={false} onImport={() => {}} onBack={() => {}} onLook={() => {}} />);
    expect(lines()).toContain('Balances 1 · 1 kept1 · Look');
    expect(screen.getByText('Balance for Mar 31 already in Steward · kept')).toBeInTheDocument();
  });

  it('says only the count when none is kept, and the Look lists account, date and amount', () => {
    const none = { ...BAL, balances: { ...BAL.balances, kept: 0, rows: [{ ...BAL.balances.rows[0], kept: false }] } };
    const { rerender } = render(<Preview reply={none} changed={false} busy={false} onImport={() => {}} onBack={() => {}} onLook={() => {}} />);
    expect(lines()).toContain('Balances 11 · Look');
    expect(screen.queryByText(/already in Steward · kept/)).toBeNull();
    rerender(<Look line="balances" reply={BAL} include={{}} simplefinOn={false} onDone={() => {}} onClose={() => {}} />);
    const sheet = screen.getByRole('dialog', { name: 'Balances' });
    expect(within(sheet).getByText(/Amex Gold · Mar 31, 2026 · .*1,234\.56 · kept/)).toBeInTheDocument();
  });
});

describe('the preview, holdings', () => {
  const HOLD = { ...PREVIEW, new: 0, writes: 3, holdings: { n: 2, kept: 1, rows: [
    { account: 'Pinecrest IRA', as_of: '2026-03-31', count: 3, kept: false }, { account: 'Brokerage', as_of: '2026-03-31', count: 4, kept: true }] } };

  it('names the statements, imports on writes, and lists what is kept', () => {
    const onLook = vi.fn();
    render(<Preview reply={HOLD} changed={false} busy={false} onImport={() => {}} onBack={() => {}} onLook={onLook} />);
    expect(screen.getByText('Holdings 2 statements')).toBeInTheDocument();
    expect(screen.getByText('Holdings for Mar 31 already in Steward · kept')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Import 3' })).toBeEnabled();
    fireEvent.click(screen.getByRole('button', { name: 'Look: Holdings 2 statements' }));
    expect(onLook).toHaveBeenCalledWith('holdings');
  });

  it('says 1 statement in the singular, and the sheet lists each account', () => {
    const one = { ...HOLD, holdings: { n: 1, kept: 0, rows: [HOLD.holdings.rows[0]] } };
    const { rerender } = render(<Preview reply={one} changed={false} busy={false} onImport={() => {}} onBack={() => {}} onLook={() => {}} />);
    expect(screen.getByText('Holdings 1 statement')).toBeInTheDocument();
    const single = { ...HOLD, holdings: { ...HOLD.holdings, rows: [...HOLD.holdings.rows,
      { account: '401(k)', as_of: '2026-03-31', count: 1, kept: false }] } };
    rerender(<Look line="holdings" reply={single} include={{}} simplefinOn={false} onDone={() => {}} onClose={() => {}} />);
    const sheet = screen.getByRole('dialog', { name: 'Holdings' });
    expect(within(sheet).getByText('Pinecrest IRA · Mar 31, 2026: 3 holdings')).toBeInTheDocument();
    expect(within(sheet).getByText('Brokerage · Mar 31, 2026: 4 holdings · kept')).toBeInTheDocument();
    expect(within(sheet).getByText('401(k) · Mar 31, 2026: 1 holding')).toBeInTheDocument();
  });
});

function LookHost({ line, onDone }: { line: LookLine; onDone: (include: Record<string, number[]>, on: boolean) => void }) {
  const [open, setOpen] = useState(true);
  return open ? <Look line={line} reply={PREVIEW} include={{}} simplefinOn={false} onDone={(i, s) => { onDone(i, s); setOpen(false); }} onClose={() => setOpen(false)} /> : null;
}

describe('Look', () => {
  it('Import anyway chooses a row that looks the same', () => {
    const onDone = vi.fn();
    render(<LookHost line="same" onDone={onDone} />);
    const sheet = screen.getByRole('dialog', { name: 'Looks the same' });
    expect(within(sheet).getByText(/In Steward: Mar 1, 2024 · COFFEE CORNER · −\$4\.50/)).toBeInTheDocument();
    fireEvent.click(within(sheet).getByRole('checkbox', { name: 'Import anyway' }));
    fireEvent.click(within(sheet).getByRole('button', { name: 'Done' }));
    expect(onDone).toHaveBeenCalledWith({ f_a: [17] }, false);
  });

  it('Import these too takes the SimpleFIN rows', () => {
    const onDone = vi.fn();
    render(<LookHost line="simplefin" onDone={onDone} />);
    const sheet = screen.getByRole('dialog', { name: 'SimpleFIN already has these' });
    expect(within(sheet).getByText('SimpleFIN has this account from Aug 4')).toBeInTheDocument();
    fireEvent.click(within(sheet).getByRole('switch', { name: 'Import these too' }));
    fireEvent.click(within(sheet).getByRole('button', { name: 'Done' }));
    expect(onDone).toHaveBeenCalledWith({}, true);
  });

  it('Already is read-only and says how many aren’t shown', () => {
    render(<LookHost line="already" onDone={() => {}} />);
    const sheet = screen.getByRole('dialog', { name: 'Already in Steward' });
    expect(within(sheet).queryByRole('checkbox')).toBeNull();
    expect(within(sheet).getByText("317 more aren't shown")).toBeInTheDocument();
  });
});
