import { screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { stubFetch, wrapBook } from '../../test-utils';
import type { RothOut } from './api';
import { RothCard } from './RothCard';

afterEach(() => vi.unstubAllGlobals());

const R: RothOut = {
  available: true, year: 2026, rate_now: 0.12, rate_later: 0.22, lean: 'roth', line: 'Roth this year: 12% now against about 22% later.',
  later_line: 'From retiring at 63 (the Likely age in the plan saved Oct 7), with required withdrawals from 2057 and Social Security.',
  conversion: { amount_cents: 1700000, tax_cents: 204000, line: "This year's rate is low: converting $17,000 of traditional money to Roth would cost about $2,040 in tax, filling the 10% federal bracket (2026 rules)." },
  rules_note: '2026 federal and 2025 California rules', notes: [], never: 'Steward never pays or files anything.',
};

describe('The Roth or traditional card', () => {
  it('leans with the numbers and flags a conversion', async () => {
    stubFetch({ '/api/taxes/roth': R });
    wrapBook(<RothCard />);
    expect(await screen.findByRole('heading', { name: 'Roth or traditional' })).toBeInTheDocument();
    expect(screen.getByText('Roth this year: 12% now against about 22% later.')).toBeInTheDocument();
    expect(screen.getByText('12%')).toBeInTheDocument();
    expect(screen.getByText('About 22%')).toBeInTheDocument();
    expect(screen.getByText(R.later_line!)).toBeInTheDocument();
    expect(screen.getByText(R.conversion!.line)).toBeInTheDocument();
  });
  it('without a rate later, says why', async () => {
    stubFetch({ '/api/taxes/roth': { ...R, rate_later: null, lean: 'either', conversion: null, later_line: 'Finish Plan setup to compare with retirement.',
      line: "Traditional saves 31% of each dollar in tax this year; there's no retirement estimate to compare with yet." } });
    wrapBook(<RothCard />);
    expect(await screen.findByText('Finish Plan setup to compare with retirement.')).toBeInTheDocument();
    expect(screen.queryByText('Rate later')).toBeNull();
  });
});
