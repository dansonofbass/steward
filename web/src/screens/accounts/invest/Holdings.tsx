import type { ReactNode } from 'react';
import { dollars } from '../../../lib/format';
import { rich } from '../../../lib/receipt';
import { Button } from '../../../ui/Button';
import { Rich } from '../../../ui/Rich';
import type { HoldingRow, HoldingsOut, InvestmentPage } from './api';
import {
  ADVISORY_LINE, ALL_IN, CLASS_LABELS, COST_A_YEAR, COST_UNKNOWN, FUND, IMPORT_POSITIONS, IMPORT_PROMPT, INVESTED_IN,
  NOT_COUNTING_N, NOT_COUNTING_ONE, VALUE,
} from './copy';
import { bpText, sourceLine } from './format';

/** The mix bar (investment views spec): US stocks, International, Bonds, Cash and Other, from asset_classes. */
export function MixBar({ mix }: { mix: HoldingsOut['mix'] }) {
  const sum = mix.reduce((s, p) => s + p.cents, 0) || 1;
  return (
    <div className="mixbar">
      <div className="mixbar__bar" aria-hidden="true">
        {mix.map((p) => <span key={p.class} className={`mixbar__seg is-${p.class}`} style={{ flexGrow: p.cents }} />)}
      </div>
      <ul className="mixbar__keys">
        {mix.map((p) => (
          <li key={p.class}><span className={`mixbar__dot is-${p.class}`} aria-hidden="true" />{`${CLASS_LABELS[p.class]} ${Math.round((p.cents * 100) / sum)}%`}</li>
        ))}
      </ul>
    </div>
  );
}

type Props = {
  page: InvestmentPage;
  /** Import positions (managers only; Task 9). Without it the prompt shows and the button doesn't. */
  onImport?: () => void;
  /** What an unknown cost's cell shows ("cost unknown · Add" for a manager; Task 9). */
  cost?: (row: HoldingRow) => ReactNode;
  /** The advisory fee's line, editable for a manager (Task 9). */
  fee?: ReactNode;
  /** The first import's cheer (Task 12). */
  cheer?: ReactNode;
};

/** "What it's invested in" (investment views spec): the mix, the funds with their value and cost a year, the advisory
 *  fee, all in, and where the holdings came from; without holdings, what an import would show. */
export function Holdings({ page, onImport, cost, fee, cheer }: Props) {
  const h = page.holdings;
  const today = new Date();
  const feeLine = fee ?? (page.advisory && (
    <p className="inv-fee">{ADVISORY_LINE.replace('{pct}', bpText(page.advisory.fee_bp)).replace('{amount}', dollars(page.advisory.cost_cents))}</p>
  ));
  return (
    <section className="inv-sec" aria-labelledby="inv-held-h">
      <h2 id="inv-held-h">{INVESTED_IN}</h2>
      {cheer}
      {h ? (
        <>
          <MixBar mix={h.mix} />
          <table className="inv-table">
            <thead><tr><th scope="col">{FUND}</th><th scope="col">{VALUE}</th><th scope="col">{COST_A_YEAR}</th></tr></thead>
            <tbody>
              {h.rows.map((r) => (
                <tr key={r.id}>
                  <th scope="row">{r.symbol && <span className="inv-sym">{r.symbol}</span>}<span className="inv-name">{r.name}</span></th>
                  <td>{dollars(r.value_cents)}</td>
                  <td className="inv-cost">{r.cost_cents !== null ? dollars(r.cost_cents) : cost ? cost(r) : <span className="muted">{COST_UNKNOWN}</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {feeLine}
          {page.all_in && <p className="inv-allin"><Rich parts={rich(ALL_IN, { amount: dollars(page.all_in.cents), pct: page.all_in.pct })} /></p>}
          {h.unknown > 0 && <p className="small muted">{h.unknown === 1 ? NOT_COUNTING_ONE : NOT_COUNTING_N.replace('{n}', String(h.unknown))}</p>}
          <p className="small muted">{sourceLine(h, page.institution, today)}</p>
          {onImport && <Button variant="quiet" onClick={onImport}>{IMPORT_POSITIONS}</Button>}
        </>
      ) : (
        <>
          <p>{IMPORT_PROMPT.replace('{institution}', page.institution)}</p>
          {onImport && <Button onClick={onImport}>{IMPORT_POSITIONS}</Button>}
          {feeLine}
        </>
      )}
    </section>
  );
}
