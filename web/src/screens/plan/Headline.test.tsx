import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { planFixture } from './fixtures';
import { Headline, monthlySpend } from './Headline';

describe('the Plan in one sentence (roadmap 14)', () => {
  it("says the Comfortably age, the month's living costs in today's dollars, what the plan pays on top, and the odds", () => {
    const { result } = planFixture();
    // $88,400 a year at 100% is $7,367 a month, to the nearest $100.
    render(<Headline result={result} basisCents={8_840_000} spendingPct={100} younger="Sam" />);
    expect(screen.getByTestId('plan-headline')).toHaveTextContent(
      "Retire at 63, with about $7,400 a month for living costs in today's dollars." +
      'The plan also pays the mortgage until it ends, health insurance and big one-off costs. ' +
      'In 9 of 10 simulated market histories, the money lasts until Sam is 95.');
  });

  it('follows the Spending in retirement lever', () => {
    expect(monthlySpend(8_840_000, 90)).toBe(660_000);    // $6,630 rounds to $6,600
    expect(monthlySpend(12_000_000, 100)).toBe(1_000_000);
  });

  it('says plainly when no age works by 70', () => {
    const { result } = planFixture();
    render(<Headline result={{ ...result, comfortable_age: null }} basisCents={8_840_000} spendingPct={100} younger="Sam" />);
    expect(screen.getByTestId('plan-headline')).toHaveTextContent(
      "Not by 70 with about $7,400 a month for living costs in today's dollars.Try changes shows what brings it closer.");
  });
});
