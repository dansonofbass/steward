import { describe, expect, it } from 'vitest';
import { confirmedBy, confirmedNote, parsePay, parsePremium, payFormFrom, payPreview, savedNote } from './facts';

const f = (value: string) => ({ value, as_of: '2026-10-12', note: null });

describe('pay', () => {
  it('turns the form into five facts in cents and basis points', () => {
    expect(parsePay({ salary: '165,000', k401: '8', roth: '', matchRate: '50', matchCap: '6' }, 'JR')).toEqual({ facts: [
      { key: 'jr.salary_cents', value: '16500000' },
      { key: 'jr.k401_pct_bp', value: '800' },
      { key: 'jr.k401_roth_share_bp', value: '0' },
      { key: 'employer.match_rate_bp', value: '5000' },
      { key: 'employer.match_cap_bp', value: '600' },
    ] });
  });
  it('says what is wrong in plain words', () => {
    expect(parsePay({ salary: '', k401: '120', roth: '0', matchRate: 'x', matchCap: '6' }, 'JR')).toEqual({ errors: {
      salary: "Enter JR's yearly salary before deductions.",
      k401: 'Enter a percentage between 0 and 100.',
      matchRate: 'Enter a percentage between 0 and 100.',
    } });
  });
  it('fills the form from saved facts', () => {
    expect(payFormFrom({ 'jr.salary_cents': f('16500000'), 'jr.k401_pct_bp': f('800'), 'employer.match_rate_bp': f('5000'), 'employer.match_cap_bp': f('600') }))
      .toEqual({ salary: '165,000', k401: '8', roth: '0', matchRate: '50', matchCap: '6' });
  });
  it('shows the contribution and the employer match in dollars as you type', () => {
    expect(payPreview({ salary: '165,000', k401: '8', roth: '0', matchRate: '50', matchCap: '6' })).toEqual({ contribution: 1_320_000, match: 495_000 });
    expect(payPreview({ salary: '165,000', k401: '8', roth: '0', matchRate: '', matchCap: '6' })).toEqual({ contribution: 1_320_000, match: null });
    expect(payPreview({ salary: '', k401: '8', roth: '0', matchRate: '50', matchCap: '6' })).toEqual({ contribution: null, match: null });
  });
});

describe('health', () => {
  it('reads a yearly premium', () => {
    expect(parsePremium('16,800')).toEqual({ cents: 1680000 });
    expect(parsePremium('')).toEqual({ error: 'Enter the yearly premium.' });
  });
});

describe('notes', () => {
  it('writes and reads the confirmation note', () => {
    expect(savedNote('JR')).toBe('Saved by JR');
    expect(confirmedNote('JR')).toBe('Confirmed by JR');
    expect(confirmedBy(confirmedNote('JR'))).toBe('JR');
    expect(confirmedBy('Saved by JR')).toBeUndefined();
    expect(confirmedBy(undefined)).toBeUndefined();
  });
});
