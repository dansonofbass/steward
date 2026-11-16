import { Undo2 } from 'lucide-react';
import { UNDO } from '../../lib/copy';
import type { ReviewView } from '../../lib/reviewPrefs';
import { useWide } from '../../lib/useWide';
import { Button } from '../../ui/Button';
import { Sep } from '../../ui/Sep';
import { N_LEFT, VIEW_FOCUS, VIEW_GROUP, VIEW_LIST } from './copy';

/** A fine pointer that hovers: the keys line, chip numbers and aria-keyshortcuts show (P24). */
export const FINE = '(hover: hover) and (pointer: fine)';

type Props = {
  left: number;
  /** Absent for a viewer: no Undo. */
  undo?: { can: boolean; busy: boolean; run: () => void };
  /** Absent for a viewer (P3): no toggle. */
  view?: { is: ReviewView; set: (v: ReviewView) => void };
  /** Focus only: done / (done + left), 0 to 1 (P31). */
  progress?: number | null;
};

/** Review focus, The top bar (both views): "↶ Undo · 12 left", the Focus | List toggle, and in focus the progress bar.
 *  Undo is disabled, not hidden, when there is nothing to undo, so the bar never shifts (P28). */
export function TopBar({ left, undo, view, progress = null }: Props) {
  const fine = useWide(FINE);
  return (
    <div className="rtop" data-testid="review-top">
      <p className="rtop__line">
        {undo && (
          <>
            <Button variant="quiet" className="rtop__undo" icon={Undo2} disabled={!undo.can} busy={undo.busy}
              aria-keyshortcuts={fine ? 'Z' : undefined} onClick={undo.run}>{UNDO}</Button>
            <Sep />
          </>
        )}
        <span className="rtop__left">{N_LEFT.replace('{n}', String(left))}</span>
      </p>
      {view && (
        <div className="rtop__view" role="group" aria-label={VIEW_GROUP}>
          <button type="button" aria-pressed={view.is === 'focus'} onClick={() => { view.set('focus'); }}>{VIEW_FOCUS}</button>
          <button type="button" aria-pressed={view.is === 'list'} onClick={() => { view.set('list'); }}>{VIEW_LIST}</button>
        </div>
      )}
      {progress !== null && (
        <div className="rtop__track" aria-hidden="true"><span className="rtop__fill" style={{ transform: `scaleX(${progress})` }} /></div>
      )}
    </div>
  );
}
