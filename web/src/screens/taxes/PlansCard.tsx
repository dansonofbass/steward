import { useState } from 'react';
import { dollars } from '../../lib/format';
import { Card } from '../../ui/Card';
import { Notice } from '../../ui/Notice';
import { Skeleton } from '../../ui/Skeleton';
import { usePlans, type PlanPointOut } from './api';
import * as C from './copy';

type Row = { label: string; solo: number; sep: number | null };

function rows(p: PlanPointOut, year: number): Row[] {
  const out: Row[] = [{ label: C.OWN, solo: p.solo.own_cents, sep: null }];
  if (p.solo.catch_up_cents > 0) out.push({ label: C.CATCH_UP, solo: p.solo.catch_up_cents, sep: null });
  out.push({ label: C.BUSINESS_PART, solo: p.solo.business_cents, sep: p.sep.total_cents },
    { label: C.MOST, solo: p.solo.total_cents, sep: p.sep.total_cents },
    { label: C.SAVES.replace('{year}', String(year)), solo: p.solo.saves_cents, sep: p.sep.saves_cents });
  return out;
}

/** Spec 7.2: the room from profit so far and the range, Solo 401(k) and SEP side by side, the tax each lowers, and
 *  the deadlines in plain words. A three-column table stays inside 320 px; the chips pick the profit. */
export function PlansCard() {
  const q = usePlans();
  const [chosen, setChosen] = useState<string | null>(null);
  if (q.isError) return <Card><Notice tone="error"><p>{q.error.message}</p></Notice></Card>;
  if (!q.data) return <Card><Skeleton lines={4} /></Card>;
  const d = q.data;
  if (!d.available) return <Card className="stack"><h2>{C.PLANS}</h2><p className="muted">{d.reason}</p></Card>;
  const point = d.points.find((p) => p.label === (chosen ?? d.default_point)) ?? d.points[0];
  return (
    <Card className="stack">
      <h2>{C.PLANS}</h2>
      {d.points.length > 1 && (
        <div className="seg tax-seg" role="group" aria-label={C.PROFIT_POINT}>
          {d.points.map((p) => (
            <button key={p.label} type="button" className={p.label === point.label ? 'is-on' : undefined} aria-pressed={p.label === point.label} onClick={() => setChosen(p.label)}>
              {p.label_text}
            </button>
          ))}
        </div>
      )}
      <p>{`${C.PROFIT_FOR[point.label]}: ${dollars(point.profit_cents)}`}</p>
      <table className="tax-table">
        <thead><tr><th scope="col" /><th scope="col">{C.SOLO}</th><th scope="col">{C.SEP}</th></tr></thead>
        <tbody>
          {rows(point, d.year).map((r) => (
            <tr key={r.label}><th scope="row">{r.label}</th><td>{dollars(r.solo)}</td><td>{r.sep === null ? C.NONE : dollars(r.sep)}</td></tr>
          ))}
        </tbody>
      </table>
      <p>{point.line}</p>
      <section className="stack stack--tight">
        <h3>{C.DEADLINES}</h3>
        <p className="small strong">{C.SOLO}</p>
        <ul className="tax-list">{d.deadlines.solo.map((t) => <li key={t}><span>{t}</span></li>)}</ul>
        <p className="small strong">{C.SEP}</p>
        <ul className="tax-list">{d.deadlines.sep.map((t) => <li key={t}><span>{t}</span></li>)}</ul>
      </section>
      {d.notes.map((n) => <p key={n} className="small muted">{n}</p>)}
      <p className="small muted">{d.rules_note}</p>
    </Card>
  );
}
