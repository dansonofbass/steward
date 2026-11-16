import { screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { redMonth, type HomeData } from '../../api/home';
import { wrapBook } from '../../test-utils';
import { HOME, homeWith } from './fixtures';
import { barWidths, greeting, paydayMoment, Verdict } from './Verdict';

const flow = (in_cents: number, out_cents: number, payday: HomeData['flow']['payday'] = null) =>
  homeWith({ flow: { ...HOME.flow, in_cents, out_cents, net_cents: in_cents - out_cents, payday } });
const BEST = homeWith({ verdict: { ...HOME.verdict, best_month: true } });
const reduce = () => vi.stubGlobal('matchMedia', (q: string) => ({ matches: q.includes('reduce'), media: q, addEventListener: () => {}, removeEventListener: () => {} }));
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  localStorage.removeItem('steward-home-best');
  localStorage.removeItem('steward-celebrations');
});

describe('Verdict (Home spec, section 1)', () => {
  it("heads Home with the server's day, never the browser's, and the headline as the h1", () => {
    wrapBook(<Verdict data={homeWith({ as_of: '2026-10-27' })} ready />);
    expect(screen.getByText('Tuesday, Oct 27')).toBeInTheDocument();          // the browser's clock says Friday, Oct 30
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent("A steady month. Spending's on track, bills are paid, and the plan still says 54.");
    expect(screen.getByTestId('verdict')).toHaveAttribute('data-ready', 'true');
  });

  it('is not ready until Home is', () => {
    wrapBook(<Verdict data={HOME} ready={false} />);
    expect(screen.getByTestId('verdict')).not.toHaveAttribute('data-ready');
  });

  it('in the black: the figure in ink, the bar, the legend, and the block opens Spending on this month', () => {
    wrapBook(<Verdict data={HOME} ready />);
    const figure = screen.getByTestId('figure');
    expect(figure).toHaveTextContent('$1,240 in the black so far this month');
    expect(figure).toHaveClass('is-black');
    expect(screen.getByText('$6,380 in')).toBeInTheDocument();
    expect(screen.getByText('$5,140 out')).toBeInTheDocument();
    expect(figure.closest('a')).toHaveAttribute('href', '/b/ours/spending?month=2026-10');
    expect(document.querySelector('.verdict__bar')).toHaveAttribute('aria-hidden', 'true');
  });

  it('in the red: the words say so, in amber (--warn), never red', () => {
    wrapBook(<Verdict data={flow(210_000, 251_000)} ready />);
    const figure = screen.getByTestId('figure');
    expect(figure).toHaveTextContent('$410 in the red so far this month');
    expect(figure).toHaveClass('is-red');
  });

  it('even, and nothing in or out yet (with no bar)', () => {
    const even = wrapBook(<Verdict data={flow(100_000, 100_000)} ready />);
    expect(screen.getByTestId('figure')).toHaveTextContent('Even so far this month');
    expect(document.querySelector('.verdict__bar')).not.toBeNull();
    even.unmount();
    wrapBook(<Verdict data={flow(0, 0)} ready />);
    expect(screen.getByTestId('figure')).toHaveTextContent('Nothing in or out yet this month.');
    expect(document.querySelector('.verdict__bar')).toBeNull();
    expect(screen.queryByText(/ in$/)).toBeNull();
  });

  it("draws the bar's two widths, a side with money at least 2% wide", () => {
    expect(barWidths(1, 99_999)).toEqual({ in: 2, out: 98 });
    expect(barWidths(99_999, 1)).toEqual({ in: 98, out: 2 });
    expect(barWidths(0, 5_000)).toEqual({ in: 0, out: 100 });
    expect(barWidths(0, 0)).toBeNull();
    const w = barWidths(638_000, 514_000)!;
    expect(w.in).toBeCloseTo(55.38, 2);
    expect(w.in + w.out).toBeCloseTo(100, 10);
    wrapBook(<Verdict data={flow(1, 99_999)} ready />);
    expect((document.querySelector('.verdict__in') as HTMLElement).style.width).toBe('2%');
  });

  it("says the usual payday when it hasn't come, and nothing otherwise", () => {
    const fifteenth = wrapBook(<Verdict data={flow(210_000, 251_000, { day: 15 })} ready />);
    expect(screen.getByText("Payday's usually the 15th.")).toBeInTheDocument();
    fifteenth.unmount();
    const first = wrapBook(<Verdict data={flow(210_000, 251_000, { day: 1 })} ready />);
    expect(screen.getByText("Payday's usually the 1st.")).toBeInTheDocument();
    first.unmount();
    wrapBook(<Verdict data={HOME} ready />);
    expect(screen.queryByText(/^Payday's usually/)).toBeNull();
  });

  it('the joy line fades in the first time it shows this month on this device, then stays still', () => {
    const first = wrapBook(<Verdict data={BEST} ready />);
    expect(screen.getByTestId('joy')).toHaveTextContent('Already your best month in a year.');
    expect(screen.getByTestId('joy')).toHaveClass('is-new');
    expect(localStorage.getItem('steward-home-best')).toBe('2026-10');
    first.unmount();
    wrapBook(<Verdict data={BEST} ready />);
    expect(screen.getByTestId('joy')).not.toHaveClass('is-new');
  });

  it('with storage refused the joy line still shows, still', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('denied'); });
    wrapBook(<Verdict data={BEST} ready />);
    expect(screen.getByTestId('joy')).toBeInTheDocument();
    expect(screen.getByTestId('joy')).not.toHaveClass('is-new');
  });

  it('under reduced motion, or with Celebrations off, the joy line has no animation', () => {
    reduce();
    const a = wrapBook(<Verdict data={BEST} ready />);
    expect(screen.getByTestId('joy')).not.toHaveClass('is-new');
    a.unmount();
    vi.unstubAllGlobals();
    localStorage.setItem('steward-celebrations', 'off');
    wrapBook(<Verdict data={BEST} ready />);
    expect(screen.getByTestId('joy')).not.toHaveClass('is-new');
  });

  it('an empty book: only the words', () => {
    wrapBook(<Verdict data={homeWith({ verdict: { ...HOME.verdict, opener: 'empty', clauses: [] }, flow: { ...HOME.flow, payday: { day: 15 } } })} ready />);
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Nothing to go on yet.');
    expect(screen.queryByTestId('figure')).toBeNull();
    expect(screen.queryByText(/^Payday's usually/)).toBeNull();
  });

  it('loading: a busy skeleton and no headline', () => {
    const { container } = wrapBook(<Verdict ready={false} />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
    expect(screen.queryByRole('heading', { level: 1 })).toBeNull();
  });
});

describe('character on Home (phase 17 spec 3.7)', () => {
  it('the date line greets by the sky phase', () => {
    wrapBook(<Verdict data={HOME} ready />);   // TEST_NOW is 12:00: day
    expect(screen.getByText(/· good day$/)).toBeInTheDocument();
  });

  it.each([[new Date(2026, 9, 30, 6, 30), 'good morning'], [new Date(2026, 9, 30, 16, 0), 'good afternoon'],
    [new Date(2026, 9, 30, 19, 0), 'good evening'], [new Date(2026, 9, 30, 22, 0), 'good evening'], [new Date(2026, 9, 30, 2, 0), 'up late']])(
    'at %s it says %s', (at, word) => { expect(greeting(at)).toBe(word); });

  it('a red month shows no greeting and no payday moment, only the plain line', () => {
    const red = homeWith({ flow: { ...HOME.flow, net_cents: -41_000, payday: { day: 15 }, payday_came: { day: 1 } } });
    wrapBook(<Verdict data={red} ready />);
    expect(screen.queryByText(/· good/)).toBeNull();
    expect(screen.queryByTestId('payday-came')).toBeNull();
    expect(screen.getByText("Payday's usually the 15th.")).toBeInTheDocument();
  });

  it('a problem in the verdict counts as money news too', () => {
    expect(redMonth(homeWith({ verdict: { ...HOME.verdict, opener: 'problem' } }))).toBe(true);
    expect(redMonth(HOME)).toBe(false);
  });

  it('the usual pay landed since the last look: a payday line with the coins, and the line again that day', async () => {
    const came = homeWith({ flow: { ...HOME.flow, net_cents: 90_000, payday: null, payday_came: { day: 1 } } });
    const first = wrapBook(<Verdict data={came} ready />);
    expect(['Payday came.', 'Payday came. Nicely done.']).toContain((await screen.findByTestId('payday-came')).textContent);
    first.unmount();
    expect(paydayMoment('ours', came.as_of, false)).toBe('again');
    expect(paydayMoment('ours', '2026-10-31', false)).toBeNull();
  });
});
