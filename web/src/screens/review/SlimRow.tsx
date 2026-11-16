import { useEffect, useRef } from 'react';
import { soundOn, withCelebrate } from '../../lib/celebrations';
import { UNDO } from '../../lib/copy';
import { Rich } from '../../ui/Rich';
import { slimText } from './toastText';
import { undoOf, type VisitRow } from './visitList';
import { Sep } from '../../ui/Sep';

/** Review focus, The list (P21): an acted card shrinks in place to one dashed line ("SORTED · {name} as {category} ·
 *  Undo") and stays until Review is left or the view switches. The stamp tag lands with a CSS keyframe (transform and
 *  opacity); a sort's celebration (streamers, the category moment, sparks) plays from the row when celebrations are on,
 *  with no second stamp. */
export function SlimRow({ row, today, undoable, onUndo }: { row: VisitRow; today: Date; undoable: boolean; onUndo: (entry: string) => void }) {
  const el = useRef<HTMLDivElement>(null);
  const o = row.outcome;
  useEffect(() => {
    const host = el.current;
    if (o.kind !== 'sorted' || !host) return;
    void withCelebrate((c) => { c.sorted({ card: host, category: o.category, applied: o.n, sound: soundOn(), mark: false }); });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once, when the card became this row
  }, []);
  const { tag, parts } = slimText(row, today);
  const entry = undoOf(o);
  return (
    <div ref={el} className="slim" data-testid="slim-row" data-id={row.id} data-outcome={o.kind}>
      <span className="stamp slim__tag">{tag}</span>
      <Sep />
      <span className="slim__text"><Rich parts={parts} /></span>
      {entry && undoable && (
        <>
          <Sep />
          <button type="button" className="link slim__undo" onClick={() => { onUndo(entry); }}>{UNDO}</button>
        </>
      )}
    </div>
  );
}
