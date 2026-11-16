import { fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { BusinessReport } from '../../api/types';
import { callsTo, stubFetch, wrapBook } from '../../test-utils';
import { NOT_ADVICE } from '../../ui/NotAdvice';
import Business from './Business';

afterEach(() => vi.unstubAllGlobals());

const REPORT: BusinessReport = {
  year: 2026, this_year: 2026, through: '2026-10-13', type: 'sole_prop', income_cents: 500000, expenses_cents: 139251, profit_cents: 360749,
  lines: [
    { key: 'income', number: '1', label: 'Income', spent_cents: 500000, counts_cents: 500000, count: 2, note: null },
    { key: 'meals', number: '24b', label: 'Meals', spent_cents: 4501, counts_cents: 2251, count: 1, note: 'Half of business meals counts (2026 rules).' },
    { key: 'software', number: '27b', label: 'Software', spent_cents: 2000, counts_cents: 2000, count: 2, note: null },
    { key: 'home_office', number: '30', label: 'Home office', spent_cents: 125000, counts_cents: 125000, count: 0, note: '300 sq ft at $5 a square foot, up to 300 (2026 rules).' },
  ],
  range: { year: 2026, ytd_cents: 360749, low_cents: 360749, high_cents: 360749, mid_cents: 360749, entered: false,
    cash_ytd_cents: 485749, cash_low_cents: 485749, cash_high_cents: 485749, cash_mid_cents: 485749, ask_expect: false },
  left_out: 1, using_note: null, home_office_limited: false,
};
const LINE = { line: { key: 'software', number: '27b', label: 'Software' }, transactions: [
  { id: 5, account_id: 2, account_name: 'Business checking', posted_at: '2026-04-03', amount_cents: -2900, raw_description: 'NOTEFLOW PRO', merchant: 'Noteflow', category: 'subscriptions', is_business: false, is_transfer: false, business_pct: 50, business_line: null, business_source: 'manual', category_source: 'rule', reviewed_at: null, from_bank: true, share_cents: -1450 },
] };

describe('The Business page', () => {
  it('shows the year so far and opens a line with its transactions', async () => {
    stubFetch({ '/api/business/lines/software': LINE, '/api/business': REPORT });
    wrapBook(<Business />, {}, '/b/ours/business');
    expect(await screen.findByRole('heading', { name: 'Business' })).toBeInTheDocument();
    expect(screen.getAllByText('$5,000.00')).toHaveLength(2);           // the summary and the Income line
    expect(screen.getByText('$3,607.49')).toBeInTheDocument();
    expect(screen.getByText('Half of business meals counts (2026 rules).')).toBeInTheDocument();
    expect(screen.getByText("1 business transaction isn't on Schedule C, such as an estimated tax payment.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Software/ }));
    expect(await screen.findByText('Noteflow')).toBeInTheDocument();
    expect(screen.getByText('$14.50 of $29.00')).toBeInTheDocument();
  });

  it('ends with the not-advice line', async () => {
    stubFetch({ '/api/business': REPORT });
    wrapBook(<Business />, {}, '/b/ours/business');
    await screen.findByRole('heading', { name: 'Business' });
    expect(await screen.findByText(NOT_ADVICE)).toBeInTheDocument();
  });

  it('lets a manager enter the rest of the year and sends whole cents', async () => {
    const fetchMock = stubFetch({ '/api/business': REPORT, 'PUT /api/business/settings': { expect: { low_cents: 800000, high_cents: 2000000 } } });
    wrapBook(<Business />, {}, '/b/ours/business');
    fireEvent.change(await screen.findByLabelText('Rest of the year, low'), { target: { value: '8,000' } });
    fireEvent.change(screen.getByLabelText('Rest of the year, high'), { target: { value: '20000' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(callsTo(fetchMock, 'PUT', '/api/business/settings')).toHaveLength(1));
    expect(callsTo(fetchMock, 'PUT', '/api/business/settings')[0].body).toEqual({ expect: { low_cents: 800000, high_cents: 2000000 } });
  });

  it('shows the range when it is entered, and no form to a viewer', async () => {
    stubFetch({ '/api/business': { ...REPORT, range: { ...REPORT.range, low_cents: 1000000, high_cents: 1600000, mid_cents: 1300000, entered: true } } });
    wrapBook(<Business />, { role: 'viewer' }, '/b/ours/business');
    expect(await screen.findByText('$10,000 to $16,000 expected')).toBeInTheDocument();
    expect(screen.queryByLabelText('Rest of the year, low')).toBeNull();
  });

  it("uses the household's year from the server, not the browser's (final review M6)", async () => {
    const LAST = { ...REPORT, year: 2030, this_year: 2031, through: '2030-12-31' };
    const fetchMock = stubFetch({ '/api/business?year=2030': LAST, '/api/business': { ...REPORT, year: 2031, this_year: 2031 } });
    wrapBook(<Business />, {}, '/b/ours/business');
    fireEvent.click(await screen.findByRole('radio', { name: '2030' }));
    expect(callsTo(fetchMock, 'GET', '/api/business')[0].url).toBe('/api/business');
    await waitFor(() => expect(callsTo(fetchMock, 'GET', '/api/business?year=2030')).toHaveLength(1));
    expect(await screen.findByText('So far in 2030')).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: '2031' })).toBeInTheDocument();
    expect(screen.queryByLabelText('Rest of the year, low')).toBeNull();       // the range is for this year only
  });

  it('shows cash profit, which the plan uses, beside the Schedule C profit (final review I3)', async () => {
    stubFetch({ '/api/business': REPORT });
    wrapBook(<Business />, {}, '/b/ours/business');
    expect(await screen.findByText('Before the home office and mileage: $4,857.49. The plan counts this, since those only lower tax.')).toBeInTheDocument();
  });

  it('says how to turn it on when the household has no business', async () => {
    stubFetch({ '/api/business': { ...REPORT, type: 'none' } });
    wrapBook(<Business />, {}, '/b/ours/business');
    expect(await screen.findByText('Business tracking is off.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Turn it on in Settings' })).toHaveAttribute('href', '/b/ours/settings/business');
  });

  it("gives a viewer no link to Settings, Business, which only a manager has", async () => {
    stubFetch({ '/api/business': { ...REPORT, type: 'none' } });
    const { unmount } = wrapBook(<Business />, { role: 'viewer' }, '/b/ours/business');
    expect(await screen.findByText('Business tracking is off. A manager can turn it on in Settings.')).toBeInTheDocument();
    expect(screen.getAllByRole('link').map((a) => a.textContent)).toEqual(['Home']);   // only the way back, nothing into Settings
    unmount();
    stubFetch({ '/api/business': REPORT });
    wrapBook(<Business />, { role: 'viewer' }, '/b/ours/business');
    expect(await screen.findByText('300 sq ft at $5 a square foot, up to 300 (2026 rules).')).toBeInTheDocument();   // the home-office line, read only
    expect(screen.getAllByRole('link').map((a) => a.textContent)).toEqual(['Home']);
    expect(screen.queryByText('Business settings')).toBeNull();
  });
});
