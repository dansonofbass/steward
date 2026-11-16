import { fireEvent, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { wrapBook } from '../../test-utils';
import MonthStrip from './MonthStrip';

const MONTHS = [
  { month: '2026-09', in_cents: 820000, out_cents: 690000, net_cents: 130000 },
  { month: '2026-10', in_cents: 300000, out_cents: 410000, net_cents: -110000 },
];
const hover = (can: boolean) => vi.stubGlobal('matchMedia', (q: string) => ({
  matches: can && q === '(hover: hover)', media: q, addEventListener: () => {}, removeEventListener: () => {} }));
afterEach(() => vi.unstubAllGlobals());

describe('the 12-month strip (JR, Oct 30: it stays, smaller, under the signs)', () => {
  it('hovering a month shows its amounts in the foot line, and leaving the strip restores it', () => {
    hover(true);
    wrapBook(<MonthStrip months={MONTHS} asOf="2026-10-14" />);
    const hits = screen.getAllByTestId('strip-hit');
    expect(hits).toHaveLength(2);
    fireEvent.mouseEnter(hits[0]);
    expect(screen.getByTestId('flow-readout')).toHaveTextContent('September: Income $8,200 · Spending $6,900 · +$1,300');
    fireEvent.mouseEnter(hits[1]);
    expect(screen.getByTestId('flow-readout')).toHaveTextContent('October so far: Income $3,000 · Spending $4,100 · −$1,100');
    fireEvent.mouseLeave(screen.getByRole('img', { name: /^Income minus spending/ }));
    expect(screen.queryByTestId('flow-readout')).toBeNull();
    expect(screen.getByTestId('flow-strip')).toHaveTextContent('September 2026');
    expect(screen.getByTestId('flow-strip')).toHaveTextContent('October 2026 so far');
  });

  it('on touch nothing changes, the strip opens Spending on this month, and its line of words is gone', () => {
    hover(false);
    wrapBook(<MonthStrip months={MONTHS} asOf="2026-10-14" />);
    fireEvent.mouseEnter(screen.getAllByTestId('strip-hit')[0]);
    expect(screen.queryByTestId('flow-readout')).toBeNull();
    expect(screen.getByTestId('flow-strip')).toHaveAttribute('href', '/b/ours/spending?month=2026-10');
    expect(screen.getByRole('img', { name: 'Income minus spending for each of the last 2 months. Income was more than spending in 1 of them.' })).toBeInTheDocument();
    expect(screen.getByTestId('flow-strip')).not.toHaveTextContent('Income $3,000');
  });
});
