import { screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { SinceData } from '../../api/home';
import { wrapBook } from '../../test-utils';
import HomeSince, { whenWord } from './HomeSince';

const SINCE: SinceData = {
  from: '2026-10-27T19:00:00+00:00', from_day: '2026-10-27', over_month: false, more: 0, net_worth_cents: 210_000,
  lines: [
    { kind: 'pay', category: 'income', name: 'Northwind payroll', n: 1, places: 1, cents: 421_200 },
    { kind: 'pay', category: 'reimbursement', name: 'Northwind', n: 1, places: 1, cents: 118_400 },
    { kind: 'bill', category: 'utilities', name: 'City Power', n: 1, places: 1, cents: -18_600 },
    { kind: 'large', category: 'shopping', name: 'Big Box Store', n: 1, places: 1, cents: -34_200 },
    { kind: 'group', category: 'dining', name: null, n: 3, places: 3, cents: -18_000 },
    { kind: 'group', category: 'personal', name: 'Bean & Leaf', n: 2, places: 1, cents: -16_000 },
  ],
};
const NOTHING: SinceData = { ...SINCE, lines: [], net_worth_cents: null };

describe('Since you last looked (Home spec, section 3)', () => {
  it("says when from the server's days, never the browser's clock", () => {
    expect(whenWord('2026-10-30', '2026-10-30', false)).toBe('earlier today');
    expect(whenWord('2026-10-29', '2026-10-30', false)).toBe('yesterday');
    expect(whenWord('2026-10-27', '2026-10-30', false)).toBe('Tuesday');
    expect(whenWord('2026-10-24', '2026-10-30', false)).toBe('Saturday');          // six days back
    expect(whenWord('2026-10-23', '2026-10-30', false)).toBe('Oct 23');            // a week back
    expect(whenWord('2026-10-12', '2026-10-30', false)).toBe('Oct 12');
    expect(whenWord('2026-09-25', '2026-10-30', true)).toBe('over a month ago');
    expect(whenWord('2026-11-01', '2026-11-02', false)).toBe('yesterday');          // the night the clocks go back
  });

  it('lists each line with a real sign, net worth last, under the heading with a <time>', () => {
    wrapBook(<HomeSince since={SINCE} asOf="2026-10-30" />);
    expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent('Since you last looked (Tuesday)');
    expect(document.querySelector('time')).toHaveAttribute('datetime', '2026-10-27');
    expect(screen.getAllByTestId('since-line').map((l) => l.textContent)).toEqual([
      'Paycheck · Northwind payroll+$4,212', 'Repaid · Northwind+$1,184', 'Utilities · City Power−$186', 'Big Box Store−$342',
      'Eating out · 3 places−$180', 'Bean & Leaf · 2 charges−$160', 'Net worth+$2,100']);
    expect(screen.queryByText(/See transactions/)).toBeNull();
  });

  it('"{n} more · See transactions" opens Transactions from the last look\'s day', () => {
    wrapBook(<HomeSince since={{ ...SINCE, more: 4 }} asOf="2026-10-30" />);
    expect(screen.getByText('4 more')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'See transactions' })).toHaveAttribute('href', '/b/ours/transactions?dates=custom&from=2026-10-27&to=2026-10-30');
  });

  it('nothing new says so once, and the card stays', () => {
    const a = wrapBook(<HomeSince since={NOTHING} asOf="2026-10-30" />);
    expect(screen.getByTestId('since-nothing')).toHaveTextContent('Nothing new since Tuesday.');
    expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent(/^Since you last looked$/);
    a.unmount();
    wrapBook(<HomeSince since={{ ...NOTHING, from_day: '2026-10-30' }} asOf="2026-10-30" />);
    expect(screen.getByTestId('since-nothing')).toHaveTextContent('Nothing new since earlier today.');
  });

  it('a last look over a month ago says so', () => {
    wrapBook(<HomeSince since={{ ...SINCE, over_month: true, from_day: '2026-09-25' }} asOf="2026-10-30" />);
    expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent('Since you last looked (over a month ago)');
  });
});
