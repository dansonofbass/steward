import type { ReactNode } from 'react';
import { dollars } from '../../lib/format';
import { Card } from '../../ui/Card';
import type { CareScenario, CareYear } from './api';
import { BalanceChart } from './BalanceChart';
import * as C from './copy';

const mediWord = (y: CareYear) => C.fill(C.MEDI_WORDS[y.medi_cal], { amount: dollars(y.medi_cal_over_cents) });

export function ScenarioCard({ s, actions }: { s: CareScenario; actions?: ReactNode }) {
  return (
    <Card className="stack care-card">
      <h3 className="care-card__title">{s.label}</h3>
      {s.levers.length > 0 && <ul className="care-levers small muted">{s.levers.map((l) => <li key={l}>{l}</li>)}</ul>}
      <p className="care-headline">{s.headline}</p>
      <BalanceChart years={s.years} runsOut={s.lasts_until === null ? null : s.lasts_until + 1} mediCal={s.medi_cal_first_year} />
      {s.care_monthly_cents > 0 && <p className="small">{C.fill(C.CARE_COST, { cost: dollars(s.care_monthly_cents) })}</p>}
      {s.cost_lines.map((l) => <p key={l} className="small muted">{l}</p>)}
      {s.ltc_line && <p className="small">{s.ltc_line}</p>}
      <p className="small">{s.medi_cal_line}</p>
      <p className="small muted">{s.medi_cal_when}</p>
      <details className="care-years">
        <summary>{C.YEAR_BY_YEAR}</summary>
        <div className="care-years__scroll">
          <table>
            <thead>
              <tr>
                <th scope="col">{C.COLS.year}</th><th scope="col">{C.COLS.balance}</th><th scope="col">{C.COLS.care}</th>
                <th scope="col">{C.COLS.ltc}</th><th scope="col">{C.COLS.tax}</th><th scope="col">{C.COLS.mediCal}</th>
              </tr>
            </thead>
            <tbody>
              {s.years.map((y) => (
                <tr key={y.year} className={y.short_cents > 0 ? 'is-short' : undefined}>
                  <th scope="row">{y.year} ({y.age})</th>
                  <td>{y.short_cents > 0 ? C.fill(C.SHORT, { amount: dollars(y.short_cents) }) : dollars(y.balance_cents)}</td>
                  <td>{dollars(y.care_cents)}</td>
                  <td>{dollars(y.ltc_cents)}</td>
                  <td>{dollars(y.tax_cents)}</td>
                  <td>{mediWord(y)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
      {actions}
    </Card>
  );
}
