import { LEGEND_CURRENT, LEGEND_DONE, LEGEND_SKIPPED, LEGEND_TODO } from '../lib/copy';
import './StepBar.css';

export type BarStatus = 'done' | 'skipped' | 'doesnt_apply' | 'todo';
type Props = { states: { key: string; status: BarStatus }[]; current?: string | null; legend?: boolean; label?: string };

const segClass = (s: BarStatus | 'current') =>
  s === 'done' || s === 'doesnt_apply' ? 'is-done' : s === 'skipped' ? 'is-skipped' : s === 'current' ? 'is-current' : 'is-todo';

/** One part per step, coloured done, this step, skipped and not started. With `label` ("Step 2 of 3") the bar is an
 *  image of that name; without one, words beside it carry the state and the bar is hidden from screen readers. */
export function StepBar({ states, current = null, legend = false, label }: Props) {
  return (
    <>
      <span className="ob-segs" data-testid="step-bar" {...(label ? { role: 'img', 'aria-label': label } : { 'aria-hidden': true })}>
        {states.map((s) => <span key={s.key} className={`ob-seg ${segClass(s.key === current ? 'current' : s.status)}`} />)}
      </span>
      {legend && (
        <span className="ob-legend" aria-hidden="true">
          <span><i className="ob-key is-done" />{LEGEND_DONE}</span>
          <span><i className="ob-key is-current" />{LEGEND_CURRENT}</span>
          <span><i className="ob-key is-skipped" />{LEGEND_SKIPPED}</span>
          <span><i className="ob-key is-todo" />{LEGEND_TODO}</span>
        </span>
      )}
    </>
  );
}
