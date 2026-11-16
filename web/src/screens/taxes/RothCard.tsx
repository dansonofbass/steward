import { Card } from '../../ui/Card';
import { Notice } from '../../ui/Notice';
import { Skeleton } from '../../ui/Skeleton';
import { pct, useRoth } from './api';
import * as C from './copy';

/** Spec 7.3: this year's rate against the expected rate in retirement, a lean with the numbers, and in a low-income
 *  year the conversion and what it would cost. Steward never moves money. */
export function RothCard() {
  const q = useRoth();
  if (q.isError) return <Card><Notice tone="error"><p>{q.error.message}</p></Notice></Card>;
  if (!q.data) return <Card><Skeleton lines={3} /></Card>;
  const d = q.data;
  if (!d.available) return <Card className="stack"><h2>{C.ROTH}</h2><p className="muted">{d.reason}</p></Card>;
  return (
    <Card className="stack">
      <h2>{C.ROTH}</h2>
      <p className="tax-lead">{d.line}</p>
      <dl className="tax-rows">
        <div><dt>{C.RATE_NOW.replace('{year}', String(d.year))}</dt><dd>{pct(d.rate_now)}</dd></div>
        {d.rate_later !== null && <div><dt>{C.RATE_LATER}</dt><dd>{C.ABOUT.replace('{pct}', pct(d.rate_later))}</dd></div>}
      </dl>
      {d.later_line && <p className="small muted">{d.later_line}</p>}
      {d.conversion && <Notice><p>{d.conversion.line}</p></Notice>}
      {d.notes.map((n) => <p key={n} className="small muted">{n}</p>)}
      <p className="small muted">{d.rules_note}</p>
    </Card>
  );
}
