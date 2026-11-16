import { useQueryClient } from '@tanstack/react-query';
import { ListX, Undo2 } from 'lucide-react';
import { useState } from 'react';
import { useBook } from '../../book/BookContext';
import { S_DISMISSED, TRY_AGAIN } from '../../lib/copy';
import { dateLabel } from '../../lib/format';
import { Button } from '../../ui/Button';
import { Card } from '../../ui/Card';
import { Notice } from '../../ui/Notice';
import { Skeleton } from '../../ui/Skeleton';
import { failure } from '../settings/shared';
import { refreshInventory, undoSuggestion, useDismissed } from './api';
import * as C from './copy';
import { fill, parentName, possessive } from './format';
import './inventory.css';

/** "Account · Oct 16 by Jr", leaving out whichever of the date and the person is missing. */
function dismissedLine(d: { kind_label: string; answered_on: string | null; answered_by: string | null }, today: Date): string {
  const date = d.answered_on ? dateLabel(d.answered_on, today) : '';
  const who = d.answered_by ?? '';
  if (date && who) return fill(C.DISMISSED_ON, { kind: d.kind_label, date, who });
  if (date) return fill(C.DISMISSED_ON_DATE, { kind: d.kind_label, date });
  if (who) return fill(C.DISMISSED_ON_WHO, { kind: d.kind_label, who });
  return d.kind_label;
}

/** Settings, Dismissed suggestions (ruling 24): payers answered "Not <name>'s", each with Suggest again. */
export function Dismissed() {
  const book = useBook();
  const q = useDismissed();
  const qc = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  if (q.isPending) return <Card><Skeleton lines={3} /></Card>;
  if (q.isError) return <Notice tone="error"><p>{q.error.message}</p><Button variant="quiet" onClick={() => q.refetch()}>{TRY_AGAIN}</Button></Notice>;
  const today = new Date();
  const names = possessive(parentName(book));
  return (
    <section className="stack" aria-label={S_DISMISSED}>
      <h2 className="subhead"><ListX size={20} aria-hidden="true" /> {S_DISMISSED}</h2>
      <p className="muted">{fill(C.DISMISSED_LEDE, { names })}</p>
      {error && <Notice tone="error">{error}</Notice>}
      {q.data.dismissed.length === 0 ? <p className="muted">{C.NONE_DISMISSED}</p> : (
        <div className="card lines">
          {q.data.dismissed.map((d) => (
            <div key={d.id} className="line">
              <div className="line__main">
                <span>{d.payer}</span>
                <span className="small muted">{dismissedLine(d, today)}</span>
              </div>
              <Button variant="quiet" icon={Undo2} onClick={async () => {
                setError(null);
                try { await undoSuggestion(d.id); await refreshInventory(qc); } catch (e) { setError(failure(e)); }
              }}>{C.SUGGEST_AGAIN}</Button>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

export default Dismissed;
