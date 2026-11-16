// The store-names card (spec 4.4; JR decisions 2 and 6). A manager sees why Claude asks, the names that would go with
// how many rows each appears in, every row exactly as it would go and which real account each alias is; then
// "Approve for this conversation" (approved rows go with its later questions) or "Don't send". A viewer's card has no buttons.
import { Check, Store, X } from 'lucide-react';
import { useState } from 'react';
import { label as categoryLabel } from '../../lib/categories';
import { money } from '../../lib/format';
import { Button } from '../../ui/Button';
import { Notice } from '../../ui/Notice';
import { andList, answerCard, fill, orList, type Card } from './askApi';
import * as C from './copy';

const rowsWord = (n: number) => (n === 1 ? '1 row' : `${n} rows`);

export function ApprovalCard({ turnId, card }: { turnId: string; card: Card }) {
  const [busy, setBusy] = useState(false);
  const [answered, setAnswered] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function answer(send: boolean) {
    setBusy(true);
    setError(null);
    try {
      await answerCard(turnId, card.call_id, send, card.hash);
      setAnswered(true);                    // the stream's approved or declined event replaces this card
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const ask = card.rows.length ? fill(C.CARD_ROWS_ASK, { rows: rowsWord(card.rows.length), first: card.first ?? '', last: card.last ?? '' }) : C.CARD_PAYEES_ASK;
  const pairs = andList(card.accounts.map((a) => `${a.alias} is ${a.label}`));
  return (
    <div className="card approve" role="group" aria-labelledby={`card-${card.call_id}`}>
      <div className="approve__head">
        <Store size={20} aria-hidden="true" />
        <div className="stack stack--tight">
          <span id={`card-${card.call_id}`} className="approve__title">{C.CARD_TITLE}</span>
          <span>{card.reason ? `${card.reason} ${ask}` : ask}</span>
        </div>
      </div>
      <div className="stack stack--tight">
        <span className="eyebrow">{C.CARD_NAMES}</span>
        <div className="names">{card.names.map((n) => <span key={n.name} className="name">{n.name} <small>{n.count}</small></span>)}</div>
      </div>
      {card.rows.length > 0 && (
        <div className="stack stack--tight">
          <span className="eyebrow">{C.CARD_EVERY_ROW}</span>
          <table className="rows">
            <thead><tr><th>{C.COL_DATE}</th><th>{C.COL_STORE}</th><th className="num">{C.COL_AMOUNT}</th><th>{C.COL_CATEGORY}</th><th>{C.COL_ACCOUNT}</th></tr></thead>
            <tbody>
              {card.rows.map((r, i) => (
                <tr key={i}><td>{r.date}</td><td className="strong">{r.store}</td><td className="num">{money(Math.abs(r.amount_cents))}</td><td>{categoryLabel(r.category)}</td><td>{r.account}</td></tr>
              ))}
            </tbody>
          </table>
          {card.more && <p className="small muted">{C.CARD_MORE}</p>}
          {pairs && <p className="small muted">{fill(C.CARD_ACCOUNTS, { pairs })}</p>}
        </div>
      )}
      {card.payees.length > 0 && (
        <ul className="plain small">{card.payees.map((p) => <li key={p.payee}>{p.payee}: <span className="strong">{p.name}</span></li>)}</ul>
      )}
      {error && <Notice tone="error">{error}</Notice>}
      <div className="approve__acts">
        <Button icon={Check} busy={busy} disabled={answered} onClick={() => void answer(true)}>{C.APPROVE}</Button>
        <Button variant="quiet" icon={X} disabled={busy || answered} onClick={() => void answer(false)}>{C.DONT_SEND}</Button>
      </div>
      <p className="small muted">{fill(C.CARD_FOOT, { time: card.until })}</p>
    </div>
  );
}

export function ViewerCard({ managers, where }: { managers: string[]; where: string }) {
  return (
    <div className="card approve approve--viewer" role="group" aria-label={C.VIEWER_CARD_TITLE}>
      <div className="approve__head">
        <Store size={20} aria-hidden="true" />
        <div className="stack stack--tight">
          <span className="approve__title">{C.VIEWER_CARD_TITLE}</span>
          <span>{C.VIEWER_CARD_BODY}</span>
          {managers.length > 0 && <span className="small muted">{fill(C.VIEWER_CARD_WHO, { managers: orList(managers), where })}</span>}
        </div>
      </div>
    </div>
  );
}
