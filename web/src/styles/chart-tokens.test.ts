// Phase 17 (spec 2.4): money-out marks draw in --chart-out, so money in no longer recedes behind them at night; meters and
// progress bars sit on --track, which stands apart from the card; a thin fill on a track is --accent-text, which reads on
// it. In light each token equals what was there (the contrast test pins that), so light doesn't move.
import { describe, expect, it } from 'vitest';
import { readCss, rule } from '../test-css';

const WANT: readonly [file: string, selector: string, declaration: string][] = [
  ['styles/base.css', '.swatch--out', 'background: var(--chart-out)'],
  ['screens/home.css', '.verdict__out', 'background: var(--chart-out)'],
  ['screens/home/strip.css', '.strip .out', 'fill: var(--chart-out)'],
  ['screens/spending/spending.css', '.sp-chart__bar', 'fill: var(--chart-out)'],
  ['screens/spending/spending.css', '.sp-pace__fill', 'background: var(--chart-out)'],
  ['screens/spending/spending.css', '.sp-pace__bar--unsorted .sp-pace__fill', 'repeating-linear-gradient(135deg, var(--chart-out) 0 3px, transparent 3px 6px)'],
  ['screens/spending/spending.css', '.sp-pace__bar', 'background: var(--track)'],
  ['screens/plan/plan.css', '.chart .out', 'fill: var(--chart-out)'],
  ['screens/plan/plan.css', '.progress__bar', 'background: var(--track)'],
  ['screens/plan/plan.css', '.slider__rail::before', 'background: var(--track)'],
  ['screens/plan/plan.css', '.slider__fill', 'background: var(--accent-text)'],
  ['screens/chat/chat.css', '.meter', 'background: var(--track)'],
  ['screens/chat/chat.css', '.meter span', 'background: var(--accent-text)'],
  ['screens/inventory/inventory.css', '.inv-progress', 'background: var(--track)'],
  ['screens/inventory/inventory.css', '.inv-progress span', 'background: var(--accent-text)'],
  ['screens/reimburse/reimburse.css', '.rb-owed__bar', 'background: var(--track)'],
  ['screens/accounts/invest/invest.css', '.mixbar__bar', 'background: var(--track)'],
  ['ui/StepBar.css', '.ob-seg', 'background: var(--track)'],
  ['ui/StepBar.css', '.ob-key', 'background: var(--track)'],
  ['screens/profile/profile.css', '.prof-meter__bar > span', 'background: var(--accent-text)'],
  ['screens/review.css', '.rtop__fill', 'background: var(--accent-text)'],
];

describe('chart tokens (phase 17, 2.4)', () => {
  it('money out, tracks and the fills on them use the chart tokens', () => {
    const wrong = WANT.filter(([file, sel, decl]) => !rule(readCss(file), sel).includes(decl)).map(([f, s, d]) => `${f} ${s}: ${d}`);
    expect(wrong).toEqual([]);
  });
});
