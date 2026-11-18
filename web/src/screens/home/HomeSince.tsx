import type { SinceData, SinceLine } from '../../api/home';
import { Link } from '../../book/links';
import { label } from '../../lib/categories';
import { dollars } from '../../lib/format';
import * as C from './sinceCopy';
import { nothingNew, SINCE_HEAD, whenWord } from './sinceWhen';

const fill = (s: string, vars: Record<string, string | number>) => s.replace(/\{(\w+)\}/g, (_, k: string) => String(vars[k]));

/** One wording (P31): "{Category} · {payee}" for a Bill, the payee alone for a large charge, a group by places or
 *  by charges. Names only, never a note (P43). */
export function lineText(l: SinceLine): string {
  const name = l.name ?? '';
  if (l.kind === 'pay') {
    const words = l.category === 'business_income' ? C.PAY_BUSINESS : l.category === 'reimbursement' ? C.PAY_REPAID : C.PAY_INCOME;
    return fill(words, { name });
  }
  if (l.kind === 'bill') return fill(C.LINE_BILL, { category: label(l.category), name });
  if (l.kind === 'large') return name;
  return l.places > 1 || l.name === null ? fill(C.GROUP_PLACES, { category: label(l.category), n: l.places }) : fill(C.GROUP_CHARGES, { name, n: l.n });
}

/** Since you last looked (Home spec, section 3): what came in since this person's last look, six lines at most, net
 *  worth last and outside the cap. Its own chunk, loaded once Home is ready; Home leaves it out on a first visit. */
export default function HomeSince({ since, asOf }: { since: SinceData; asOf: string }) {
  const when = whenWord(since.from_day, asOf, since.over_month);
  const nothing = since.lines.length === 0 && since.net_worth_cents === null;
  return (
    <section className="card since" aria-labelledby="since-h" data-testid="since">
      <h2 id="since-h">
        {SINCE_HEAD}
        {!nothing && <>{' '}<time className="since__when muted" dateTime={since.from_day}>({when})</time></>}
      </h2>
      {nothing ? <p className="muted" data-testid="since-nothing">{nothingNew(when)}</p> : (
        <ul className="since__list">
          {since.lines.map((l, i) => (
            <li key={`${l.kind}-${i}`} className="since__row" data-testid="since-line">
              <span>{lineText(l)}</span>
              <span className={`money${l.cents > 0 ? ' money--in' : ''}`}>{dollars(l.cents, { sign: 'always' })}</span>
            </li>
          ))}
          {since.net_worth_cents !== null && (
            <li className="since__row" data-testid="since-line">
              <span>{C.SINCE_NET_WORTH}</span>
              <span className="money">{dollars(since.net_worth_cents, { sign: 'always' })}</span>
            </li>
          )}
        </ul>
      )}
      {since.more > 0 && (
        <p className="since__more small">
          <span>{fill(C.SINCE_MORE, { n: since.more })}</span>{' · '}
          <Link to={`/transactions?dates=custom&from=${since.from_day}&to=${asOf}`}>{C.SEE_TRANSACTIONS}</Link>
        </p>
      )}
    </section>
  );
}
