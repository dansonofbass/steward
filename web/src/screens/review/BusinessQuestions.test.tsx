import { fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Txn } from '../../api/types';
import { callsTo, stubFetch, wrapBook } from '../../test-utils';
import { BusinessQuestions } from './BusinessQuestions';

afterEach(() => vi.unstubAllGlobals());

const ROW: Txn = {
  id: 41, account_id: 2, account_name: 'Rewards Card', posted_at: '2026-10-03', amount_cents: -2900,
  raw_description: 'NOTEFLOW PRO', merchant: 'Noteflow', category: 'subscriptions', is_business: false,
  is_transfer: false, business_pct: 0, business_line: null, business_source: 'none', category_source: 'rule',
  reviewed_at: null, from_bank: true,
};

describe('Business or personal?', () => {
  it('sends the answer and takes the row away', async () => {
    const fetchMock = stubFetch({ 'POST /api/business/suggestions/41': { ...ROW, business_pct: 100, is_business: true } });
    wrapBook(<BusinessQuestions rows={[ROW]} today={new Date(2026, 9, 13)} />);
    expect(screen.getByRole('heading', { name: 'Business or personal?' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Business: Noteflow' }));
    await waitFor(() => expect(screen.queryByText('Noteflow')).toBeNull());
    expect(callsTo(fetchMock, 'POST', '/api/business/suggestions/41')[0].body).toEqual({ answer: 'business' });
  });

  it('an answer refreshes Spending, the strip on Home and the plan too (final review M4)', async () => {
    stubFetch({ 'POST /api/business/suggestions/41': { ...ROW, business_pct: 100, is_business: true } });
    const { qc } = wrapBook(<BusinessQuestions rows={[ROW]} today={new Date(2026, 9, 13)} />);
    const spy = vi.spyOn(qc, 'invalidateQueries');
    fireEvent.click(screen.getByRole('button', { name: 'Business: Noteflow' }));
    await waitFor(() => expect(spy).toHaveBeenCalledWith({ queryKey: ['spending'] }));   // Spending and Home's strip
    expect(spy).toHaveBeenCalledWith({ queryKey: ['plan'] });
  });

  it('shows nothing when there is nothing to ask', () => {
    stubFetch({});
    const { container } = wrapBook(<BusinessQuestions rows={[]} today={new Date(2026, 9, 13)} />);
    expect(container.textContent).toBe('');
  });
});
