import { dollars } from '../../lib/format';
import { Card } from '../../ui/Card';
import { Notice } from '../../ui/Notice';
import { Skeleton } from '../../ui/Skeleton';
import { useQuarterly, type DueOut } from './api';
import * as C from './copy';
import { EmailSwitch, Payments, ReturnForm, WithholdingForm } from './QuarterlyForms';

function DueList({ dues }: { dues: DueOut[] }) {
  return (
    <ul className="tax-list">
      {dues.map((d) => (
        <li key={d.due}>
          <span>{d.due_label}</span>
          <span className="tax-num">{dollars(d.installment_cents)}</span>
          <span className={`small tax-status tax-status--${d.status}`}>
            {d.status === 'short' ? C.SHORT.replace('{amount}', dollars(d.still_due_cents)) : C.STATUS[d.status]}
          </span>
        </li>
      ))}
    </ul>
  );
}

/** Spec 7.1: per due date, a federal and a California amount; the method Steward recommends and why; payments found;
 *  last year's return and this year's withholding; the opt-in email. Steward never pays or files anything. */
export function QuarterlyCard() {
  const q = useQuarterly();
  if (q.isError) return <Card><Notice tone="error"><p>{q.error.message}</p></Notice></Card>;
  if (!q.data) return <Card><Skeleton lines={4} /></Card>;
  const d = q.data;
  if (!d.available) return <Card className="stack"><h2>{C.QUARTERLY}</h2><p className="muted">{d.reason}</p></Card>;
  const next = d.next;
  return (
    <Card className="stack">
      <h2>{C.QUARTERLY}</h2>
      {next ? (
        <div className="stack stack--tight">
          <p className="tax-lead">{C.NEXT_DUE.replace('{date}', next.due_label)}</p>
          <dl className="tax-rows">
            {d.agencies.map((a) => (
              <div key={a.agency}><dt>{a.label}</dt><dd>{dollars(a.agency === 'federal' ? next.federal_cents : next.state_cents)}</dd></div>
            ))}
          </dl>
        </div>
      ) : <p className="tax-lead">{C.NOTHING_DUE.replace('{year}', String(d.year))}</p>}
      {d.agencies.map((a) => (
        <section key={a.agency} className="stack stack--tight">
          <h3>{a.label}</h3>
          <p>{a.line}</p>
          {a.withholding_line && <p className="small muted">{a.withholding_line}</p>}
          <DueList dues={a.dues} />
          {a.skip_line && <p className="small muted">{a.skip_line}</p>}
        </section>
      ))}
      {d.low_tax_cents !== null && <p className="small muted">{C.LOW_TAX.replace('{amount}', dollars(d.low_tax_cents))}</p>}
      <Payments data={d} />
      {d.has_wages && <WithholdingForm data={d} />}
      <ReturnForm data={d} />
      <EmailSwitch on={d.email_on} />
      {d.notes.map((n) => <p key={n} className="small muted">{n}</p>)}
      <p className="small muted">{d.rules_note}</p>
      <p className="small muted">{d.never}</p>
    </Card>
  );
}
