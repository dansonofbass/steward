import { screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { wrapBook } from '../../test-utils';
import type { ProfitRangeOut } from '../../api/types';
import { BusinessRangeLine } from './BusinessRangeLine';

const BASE: ProfitRangeOut = { year: 2026, ytd_cents: 450000, low_cents: 450000, high_cents: 450000, mid_cents: 450000, entered: false,
  cash_ytd_cents: 600000, cash_low_cents: 600000, cash_high_cents: 600000, cash_mid_cents: 600000, ask_expect: false };

describe("Plan's business line", () => {
  it('names the range and the middle the lever tries', () => {
    wrapBook(<BusinessRangeLine range={{ ...BASE, low_cents: 850000, high_cents: 1450000, mid_cents: 1150000, entered: true, cash_low_cents: 1000000, cash_high_cents: 1600000, cash_mid_cents: 1300000 }} />);
    expect(screen.getByText('Business profit for 2026, before the home office and mileage: $10,000 to $16,000 expected. The Consulting income row tries the middle, $13,000.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Business page' })).toHaveAttribute('href', '/b/ours/business');
  });
  it('without a range, says what has happened and where to add the rest', () => {
    wrapBook(<BusinessRangeLine range={BASE} />);
    expect(screen.getByText('Business profit so far in 2026, before the home office and mileage: $6,000. The Consulting income row tries that until you add what you expect for the rest of the year.')).toBeInTheDocument();
  });
  it('in January, asks for the rest of the year instead of trying a few weeks (final review M1)', () => {
    wrapBook(<BusinessRangeLine range={{ ...BASE, ytd_cents: 30000, cash_ytd_cents: 50000, cash_low_cents: 50000, cash_high_cents: 50000, cash_mid_cents: 50000, ask_expect: true }} />);
    expect(screen.getByText('Add what you expect to make in 2026 on the Business page. Until then the Consulting income row tries only what came in so far, $500.')).toBeInTheDocument();
  });
});
