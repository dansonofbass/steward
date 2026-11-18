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

  it('in November, a book that began in August shows August to November, and no empty December from last year (#34)', () => {
    hover(true);
    const year = ['2025-12', '2026-01', '2026-02', '2026-03', '2026-04', '2026-05', '2026-06', '2026-07'].map((month) => ({ month, in_cents: 0, out_cents: 0, net_cents: 0 }));
    const data = [
      { month: '2026-08', in_cents: 500000, out_cents: 400000, net_cents: 100000 },
      { month: '2026-09', in_cents: 0, out_cents: 0, net_cents: 0 },
      { month: '2026-10', in_cents: 500000, out_cents: 600000, net_cents: -100000 },
      { month: '2026-11', in_cents: 200000, out_cents: 100000, net_cents: 100000 },
    ];
    wrapBook(<MonthStrip months={[...year, ...data]} asOf="2026-11-16" />);
    expect(screen.getAllByTestId('strip-hit')).toHaveLength(4);
    expect(screen.getByRole('img', { name: 'Income minus spending for each of the last 4 months. Income was more than spending in 2 of them.' })).toBeInTheDocument();
    expect(screen.getByTestId('flow-strip')).toHaveTextContent('August 2026');
    expect(screen.getByTestId('flow-strip')).not.toHaveTextContent('December');
    fireEvent.mouseEnter(screen.getAllByTestId('strip-hit')[1]);
    expect(screen.getByTestId('flow-readout')).toHaveTextContent('September: Income $0 · Spending $0 · $0');
  });

  it('a book whose money began this month shows that month alone, and says so', () => {
    hover(false);
    const months = [{ month: '2026-10', in_cents: 0, out_cents: 0, net_cents: 0 }, { month: '2026-11', in_cents: 0, out_cents: 9000, net_cents: -9000 }];
    wrapBook(<MonthStrip months={months} asOf="2026-11-16" />);
    expect(screen.getAllByTestId('strip-hit')).toHaveLength(1);
    expect(screen.getByRole('img', { name: 'Income minus spending this month.' })).toBeInTheDocument();
    expect(screen.getByTestId('flow-strip')).toHaveTextContent(/^November 2026 so far$/);
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
