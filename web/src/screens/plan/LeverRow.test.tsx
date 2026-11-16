import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { wrapBook } from '../../test-utils';
import { ASSUMED, TRY, impactsFixture, planFixture } from './fixtures';
import { LeverRow } from './LeverRow';
import type { RowCtx } from './levers';

const ctx: RowCtx = { names: { jr: 'JR', spouse: 'Sam', joint: 'Joint' }, planYear: 2026, jrAge: 41, spouseAge: 39, younger: 'Sam', childLabels: ['Oldest', 'Middle', 'Youngest'] };
const spec = (k: string) => planFixture().lever_specs.find((s) => s.key === k)!;
const base = {
  impactsPending: false, assumed: ASSUMED, trial: TRY, saved: ASSUMED, changed: false, pinned: false, note: undefined,
  onToggle: () => {}, onAssumed: () => {}, onTry: () => {}, onTryThis: () => {}, onUnpin: () => {}, ctx, childImpacts: [],
};

describe('LeverRow', () => {
  it('reads as one line when closed: suggestion · effect', () => {
    render(<LeverRow {...base} spec={spec('save_more')} impact={impactsFixture()[1]} open={false} />);
    const head = screen.getByRole('button', { expanded: false });
    expect(head).toHaveTextContent('Save more each month');
    expect(head).toHaveTextContent('Try $500 a month');
    expect(head).toHaveTextContent('about 1 year earlier');
    expect(screen.queryByTestId('slider-save_more')).toBeNull();
  });

  it('says what last year was when the suggestion follows the vault', () => {
    render(<LeverRow {...base} spec={spec('consulting')} impact={impactsFixture()[2]} open={false} />);
    expect(screen.getByRole('button', { expanded: false })).toHaveTextContent('Your consulting last year was $18,000');
    // THO-10: the hidden dot keeps its spaces, so the name isn't "$18,000about 1 year earlier".
    expect(screen.getByRole('button', { expanded: false })).toHaveAccessibleName(/was \$18,000 \S/);
  });

  it('opens to one slider, with Try this and Change suggestion', () => {
    const onAssumed = vi.fn();
    const onTry = vi.fn();
    const onTryThis = vi.fn();
    render(<LeverRow {...base} spec={spec('save_more')} impact={undefined} open onAssumed={onAssumed} onTry={onTry} onTryThis={onTryThis} />);
    expect(screen.getByText('Working it out…')).toBeInTheDocument();
    const slider = screen.getByTestId('slider-save_more');
    expect(slider).toHaveAttribute('aria-valuetext', '$0 a month');
    expect(screen.getAllByRole('slider')).toHaveLength(1);
    fireEvent.change(slider, { target: { value: '50000' } });
    expect(onAssumed).toHaveBeenCalledWith('save_more_monthly_cents', 50000);
    fireEvent.click(screen.getByRole('button', { name: 'Try this' }));
    expect(onTryThis).toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: 'Change suggestion' }));
    expect(screen.queryByTestId('slider-save_more')).toBeNull();
    fireEvent.change(screen.getByTestId('suggest-save_more'), { target: { value: '100000' } });
    expect(onTry).toHaveBeenCalledWith('save_more_monthly_cents', 100000);
    fireEvent.click(screen.getByRole('button', { name: 'Done' }));
    expect(screen.getByTestId('slider-save_more')).toBeInTheDocument();
  });

  it('marks a changed row at its suggestion "In use", keeps a ghost where the saved value was, and disables Try this', () => {
    const { container } = render(<LeverRow {...base} spec={spec('gift')} impact={impactsFixture()[4]} open changed
      assumed={{ ...ASSUMED, gift_cents: 1000000, gift_until_year: 2036 }} />);
    expect(screen.getByText('Changed')).toBeInTheDocument();
    expect(screen.getByRole('button', { expanded: true })).toHaveTextContent('In use');
    expect(screen.getByText('Saved plan: Off')).toBeInTheDocument();
    expect(container.querySelector('.slider__ghost')).not.toBeNull();
    expect(screen.getByRole('button', { name: 'Try this' })).toBeDisabled();
  });

  it('offers "Use last year\'s amount" on a pinned gift suggestion', () => {
    const onUnpin = vi.fn();
    render(<LeverRow {...base} spec={spec('gift')} impact={impactsFixture()[4]} open pinned trial={{ ...TRY, gift_cents: 1500000 }} onUnpin={onUnpin} />);
    expect(screen.getByRole('button', { expanded: true })).toHaveTextContent('Try $15,000 a year until 2036');
    fireEvent.click(screen.getByRole('button', { name: 'Change suggestion' }));
    expect(screen.getByText('You set this suggestion.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: "Use last year's amount" }));
    expect(onUnpin).toHaveBeenCalled();
  });

  it('tags a lever with no history', () => {
    render(<LeverRow {...base} spec={spec('spouse_earnings')} impact={impactsFixture()[6]} open={false} note="No history yet" />);
    expect(screen.getByText('No history yet')).toBeInTheDocument();
    expect(screen.getByRole('button', { expanded: false })).toHaveTextContent('Try $1,000 a year from 2027 until Sam is 65');
  });

  it('college options read their dollars at each kid\'s share and living costs, with a way to change them in Profile', () => {
    const college = { growth: 0.01, children: [{ label: 'Oldest', share_pct: 50, covers_living: false }, { label: 'Middle', share_pct: 100, covers_living: true }],
      levels: { two_year: { years: 2, tuition_fees_cents: 415_000, living_cents: 1_717_000 }, in_state_public: { years: 4, tuition_fees_cents: 1_195_000, living_cents: 1_904_000 },
        out_of_state_public: { years: 4, tuition_fees_cents: 3_188_000, living_cents: 1_904_000 }, private: { years: 4, tuition_fees_cents: 4_500_000, living_cents: 2_047_000 } } };
    wrapBook(<LeverRow {...base} spec={spec('college')} impact={undefined} open ctx={{ ...ctx, childLabels: ['Oldest', 'Middle'], college }}
      assumed={{ ...ASSUMED, college_levels: ['private', 'private'] }} />);
    expect(screen.getByRole('option', { name: 'Private · about $23,000 a year' })).toBeInTheDocument();      // half of $45,000
    expect(screen.getByRole('option', { name: 'Private · about $65,000 a year' })).toBeInTheDocument();
    expect(screen.getByText('50%, tuition and fees only.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Change in Profile' })).toHaveAttribute('href', '/b/ours/profile/kids');
  });
});
