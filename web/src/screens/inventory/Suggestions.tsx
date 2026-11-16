import { useQueryClient } from '@tanstack/react-query';
import { ChevronLeft, CircleCheck, Link2, Plus, Search, Undo2, X } from 'lucide-react';
import { useState } from 'react';
import { useBook, useCanEdit } from '../../book/BookContext';
import { Link, Navigate } from '../../book/links';
import { TRY_AGAIN } from '../../lib/copy';
import { dateLabel, money } from '../../lib/format';
import { Button } from '../../ui/Button';
import { Notice } from '../../ui/Notice';
import { Sheet } from '../../ui/Sheet';
import { Skeleton } from '../../ui/Skeleton';
import { failure } from '../settings/shared';
import {
  dismissSuggestion, linkSuggestion, refreshInventory, undoSuggestion, useInventory, useSuggestions, type Answer, type ItemRow,
  type Suggestion,
} from './api';
import * as C from './copy';
import { fill, matches, parentName, possessive } from './format';
import './inventory.css';

function LinkPicker({ s, items, names, onClose, onLinked }: { s: Suggestion; items: ItemRow[]; names: string; onClose: () => void; onLinked: (a: Answer) => void }) {
  const kinds = s.kind === 'income' ? ['income', 'account'] : s.kind === 'insurance' ? ['insurance', 'account'] : ['account'];
  const open = items.filter((r) => r.status !== 'closed' && kinds.includes(r.kind));
  const likely = open.filter((r) => s.likely_ids.includes(r.id));
  const [q, setQ] = useState('');
  const [picked, setPicked] = useState<number | null>(likely[0]?.id ?? null);
  const [confirm, setConfirm] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const others = open.filter((r) => !s.likely_ids.includes(r.id) && matches(r, q));
  const chosen = open.find((r) => r.id === picked) ?? null;
  const radio = (r: ItemRow) => (
    <label key={r.id} className={`radio-row${picked === r.id ? ' is-on' : ''}`}>
      <input type="radio" name="pick" checked={picked === r.id} onChange={() => setPicked(r.id)} />
      <span className="stack stack--tight"><span className="strong">{r.name}</span><span className="small muted">{r.sub}{r.status === 'needs_checking' ? ` · ${C.STATUS_LABELS.needs_checking}` : ''}</span></span>
    </label>
  );
  async function link() {
    if (chosen === null) return;
    setBusy(true);
    setError(null);
    try {
      const { answer } = await linkSuggestion(s.id, chosen.id, confirm && chosen.status === 'needs_checking');
      onLinked(answer);
    } catch (e) {
      setError(failure(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Sheet open onClose={onClose} title={C.WHICH_ITEM}>
      <div className="stack">
        <p className="small muted">{fill(C.WILL_COUNT, { n: s.count, payer: s.payer, noun: s.noun })}</p>
        <div className="field search">
          <label className="field__label" htmlFor="pick-search">{fill(C.SEARCH_ITEMS, { names })}</label>
          <Search size={20} aria-hidden="true" />
          <input id="pick-search" value={q} placeholder={C.SEARCH_PLACEHOLDER} onChange={(e) => setQ(e.target.value)} />
        </div>
        {likely.length > 0 && <><p className="eyebrow">{C.LIKELY}</p><div className="card pick">{likely.map(radio)}</div></>}
        {others.length > 0 && <><p className="eyebrow">{C.OTHER_ITEMS}</p><div className="card pick">{others.map(radio)}</div></>}
        {chosen?.status === 'needs_checking' && (
          <label className="radio-row">
            <input type="checkbox" checked={confirm} onChange={(e) => setConfirm(e.target.checked)} />
            <span>{fill(C.ALSO_CONFIRM, { name: chosen.name })}<small className="small muted">{fill(C.CONFIRM_HINT, { noun: s.noun, payer: s.payer })}</small></span>
          </label>
        )}
        {error && <Notice tone="error">{error}</Notice>}
        <div className="row-actions">
          <Button icon={Link2} busy={busy} disabled={chosen === null} onClick={() => void link()}>{C.LINK}</Button>
          <Button variant="quiet" onClick={onClose}>{C.CANCEL}</Button>
        </div>
      </div>
    </Sheet>
  );
}

export function Suggestions() {
  const book = useBook();
  const canEdit = useCanEdit();
  const q = useSuggestions(canEdit);
  const inv = useInventory();
  const qc = useQueryClient();
  const [answers, setAnswers] = useState<Record<number, Answer>>({});
  const [picking, setPicking] = useState<Suggestion | null>(null);
  const [error, setError] = useState<string | null>(null);
  if (!canEdit) return <Navigate to="/inventory" replace />;
  if (q.isPending || inv.isPending) return <div className="screen" aria-busy="true"><Skeleton lines={6} /></div>;
  if (q.isError) return <div className="screen"><Notice tone="error"><p>{q.error.message}</p><Button variant="quiet" onClick={() => q.refetch()}>{TRY_AGAIN}</Button></Notice></div>;
  if (inv.isError) return <div className="screen"><Notice tone="error"><p>{inv.error.message}</p><Button variant="quiet" onClick={() => inv.refetch()}>{TRY_AGAIN}</Button></Notice></div>;
  const names = possessive(parentName(book));
  const list = q.data.suggestions;
  const waiting = list.filter((s) => !answers[s.id]).length;
  const today = new Date();

  async function answered(a: Answer) {
    setAnswers((m) => ({ ...m, [a.id]: a }));
    setPicking(null);
    await refreshInventory(qc, { suggestions: false });
  }
  async function act(fn: () => Promise<void>) {
    setError(null);
    try { await fn(); } catch (e) { setError(failure(e)); }
  }

  return (
    <div className="screen suggestions">
      <header className="page-head">
        <Link className="link back" to="/inventory"><ChevronLeft className="i" size={20} aria-hidden="true" />{C.BACK_TO_INVENTORY}</Link>
        <h1>{fill(C.IS_THIS_HERS, { names })}</h1>
        {list.length > 0 && <p className="muted">{fill(C.SUG_LEDE, { n: waiting, names })}</p>}
      </header>
      {error && <Notice tone="error">{error}</Notice>}
      {list.length === 0 && <p className="sorted">{C.NOTHING_TO_GO_THROUGH}</p>}
      <div className="sugs">
        {list.map((s) => {
          const a = answers[s.id];
          if (a) {
            return (
              <div key={s.id} className="card lines">
                <div className="line">
                  <div className="line__lead">
                    {a.icon === 'check' ? <CircleCheck size={20} aria-hidden="true" className="money--in" /> : <X size={20} aria-hidden="true" />}
                    <div className="line__main"><span>{a.line}</span><span className="small muted">{a.sub}</span></div>
                  </div>
                  <Button variant="quiet" icon={Undo2} onClick={() => void act(async () => {
                    await undoSuggestion(s.id);
                    setAnswers((m) => { const n = { ...m }; delete n[s.id]; return n; });
                    await refreshInventory(qc, { suggestions: false });
                  })}>{C.UNDO}</Button>
                </div>
              </div>
            );
          }
          return (
            <article key={s.id} className="card sug" aria-label={s.title}>
              <div className="sug__top">
                <p className="eyebrow">{s.eyebrow}</p>
                <h2 className="sug__title">{s.title}</h2>
                <p className="sug__why muted">{s.why}</p>
              </div>
              <div className="evid">
                {s.evidence.map((e, i) => (
                  <div key={`${i}-${e.posted_at}-${e.raw}`} className="txn">
                    <span className="txn__name is-raw">{e.raw}</span>
                    <span className={`money money--m${e.amount_cents > 0 ? ' money--in' : ''}`}>{money(e.amount_cents, { sign: e.amount_cents > 0 ? 'always' : 'never' })}</span>
                    <span className="txn__meta">{dateLabel(e.posted_at, today)} · {e.account}</span>
                  </div>
                ))}
                {s.forms.map((f) => <div key={f} className="txn"><span className="txn__name">{f}</span></div>)}
              </div>
              <div className="sug__acts">
                <Link className="btn btn--primary" to={`/inventory/new?suggestion=${s.id}`}>
                  <span className="btn__content"><Plus size={20} aria-hidden="true" /><span>{fill(C.ADD_AS, { kind: C.KIND_LABELS[s.kind].toLowerCase() })}</span></span>
                </Link>
                <Button variant="quiet" icon={Link2} onClick={() => setPicking(s)}>{C.ALREADY_LISTED}</Button>
                <Button variant="quiet" icon={X} onClick={() => void act(async () => answered((await dismissSuggestion(s.id)).answer))}>{fill(C.NOT_HERS, { names })}</Button>
              </div>
            </article>
          );
        })}
      </div>
      {picking && <LinkPicker s={picking} items={inv.data?.items ?? []} names={names} onClose={() => setPicking(null)} onLinked={(a) => void answered(a)} />}
    </div>
  );
}

export default Suggestions;
