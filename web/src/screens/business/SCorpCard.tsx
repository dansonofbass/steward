import { useQuery } from '@tanstack/react-query';
import { api } from '../../api/client';
import type { ScorpOut, ScorpPoint } from '../../api/types';
import { dollars } from '../../lib/format';
import { Card } from '../../ui/Card';
import { Skeleton } from '../../ui/Skeleton';
import * as C from './copy';

const ROWS: { label: string; value: (p: ScorpPoint) => string }[] = [
  { label: C.PROFIT, value: (p) => dollars(p.profit_cents) },
  { label: C.SCORP_SOLE, value: (p) => dollars(p.sole_tax_cents) },
  { label: C.SCORP_WITH, value: (p) => dollars(p.scorp_tax_cents + p.cost_cents) },
  { label: C.SCORP_DIFF, value: (p) => dollars(p.saves_cents, { sign: 'always' }) },
];

/** Spec 5.4: the saving at the profit range, or "not yet worth it". Steward compares; it never runs payroll.
 *  A table on wider screens; one stacked block per point on a phone, so nothing scrolls sideways at 320 px. */
export function SCorpCard({ year }: { year: number }) {
  const q = useQuery({ queryKey: ['business', year, 's-corp'], queryFn: () => api<ScorpOut>(`/api/business/s-corp?year=${year}`) });
  if (q.isError) return null;
  if (!q.data) return <Card><Skeleton lines={3} /></Card>;
  const d = q.data;
  return (
    <Card className="stack">
      <h2>{C.SCORP_TITLE}</h2>
      {!d.available ? <p className="muted">{d.reason}</p> : (
        <>
          <p className="biz-range">{d.line}</p>
          <table className="biz-table biz-table--wide">
            <thead>
              <tr><th scope="col" />{d.points.map((p) => <th key={p.label} scope="col">{C.POINT_LABEL[p.label]}</th>)}</tr>
            </thead>
            <tbody>
              {ROWS.map((r) => (
                <tr key={r.label}><th scope="row">{r.label}</th>{d.points.map((p) => <td key={p.label}>{r.value(p)}</td>)}</tr>
              ))}
            </tbody>
          </table>
          <div className="biz-points">
            {d.points.map((p) => (
              <section key={p.label} className="biz-point">
                <h3>{C.POINT_LABEL[p.label]}</h3>
                <dl>
                  {ROWS.map((r) => (
                    <div key={r.label}><dt>{r.label}</dt><dd>{r.value(p)}</dd></div>
                  ))}
                </dl>
              </section>
            ))}
          </div>
          <p className="small muted">{C.SCORP_HOW.replace('{pct}', String(d.salary_pct)).replace('{cost}', dollars(d.cost_cents))}</p>
          {d.state_note && <p className="small muted">{d.state_note}</p>}
          <p className="small muted">{d.rules_note}</p>
          <p className="small muted">{C.SCORP_ASK}</p>
        </>
      )}
    </Card>
  );
}
