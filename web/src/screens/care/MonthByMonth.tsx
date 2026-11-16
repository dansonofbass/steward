import { label } from '../../lib/categories';
import { dateLabel, dollars, monthLabel } from '../../lib/format';
import { Card } from '../../ui/Card';
import { Money } from '../../ui/Money';
import { Notice } from '../../ui/Notice';
import type { Monthly } from './api';
import * as C from './copy';

/** Spec 4.4: what's expected in the next 60 days, recent months by category, and the short line. */
export function MonthByMonth({ m }: { m: Monthly }) {
  const today = new Date();
  const recent = [...m.months].reverse();
  return (
    <section className="stack" aria-labelledby="care-months">
      <h2 id="care-months">{C.MONTH_BY_MONTH}</h2>
      {m.short_line && <Notice tone="warn">{m.short_line}</Notice>}
      <div className="care-cols">
        <Card className="stack">
          <h3 className="eyebrow">{C.NEXT_60}</h3>
          {m.expected.length === 0 ? <p className="small muted">{C.NOTHING_EXPECTED}</p> : (
            <ul className="care-expected">
              {m.expected.map((e, i) => (
                <li key={`${e.on}-${i}`}>
                  <span className="small muted">{dateLabel(e.on, today)}</span>
                  <span>{e.label}</span>
                  <Money cents={e.cents} sign="always" />
                </li>
              ))}
            </ul>
          )}
          <p className="small">{C.fill(C.COMING, { in: dollars(m.expected_in_cents), out: dollars(m.expected_out_cents) })}</p>
          <p className="small muted">{C.fill(m.floors_cents > 0 ? C.ABOVE_FLOOR : C.CASH_ON_HAND, { cash: dollars(m.above_floor_cents) })}</p>
          {m.undated_line && <p className="small muted">{m.undated_line}</p>}
        </Card>
        <Card className="stack">
          <h3 className="eyebrow">{C.RECENT}</h3>
          <ul className="care-months">
            {recent.map((r, i) => (
              <li key={r.month}>
                <details>
                  <summary>
                    <span>{monthLabel(`${r.month}-01`)}{i === 0 ? C.SO_FAR : ''}</span>
                    <span className="small">{C.fill(C.IN_OUT, { in: dollars(r.in_cents), out: dollars(r.out_cents) })}</span>
                  </summary>
                  <ul className="small">
                    {r.categories.map((c) => (
                      <li key={c.category}><span>{label(c.category)}</span><span>{c.out_cents ? dollars(-c.out_cents) : dollars(c.in_cents, { sign: 'always' })}</span></li>
                    ))}
                  </ul>
                </details>
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </section>
  );
}
