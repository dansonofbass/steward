import { useQueryClient } from '@tanstack/react-query';
import { useRef, useState, type MouseEvent } from 'react';
import { undoToken } from '../../../api/profile';
import { addMany, dismissSuggestion, invalidateSetAsides, restoreSuggestion } from '../../../api/setasides';
import type { SetAsideBody, SetAsideGroup, SetAsideList, SetAsideSuggestion } from '../../../api/types';
import { Link } from '../../../book/links';
import { collapse } from '../../../lib/collapse';
import { dollars } from '../../../lib/format';
import { picked } from '../../../lib/selection';
import { Button } from '../../../ui/Button';
import { Notice } from '../../../ui/Notice';
import { UndoToast } from '../../../ui/UndoToast';
import * as C from './copy';
import { fill, suggestionWhen } from './model';
import { DismissedRow, suggestionHref } from './parts';

const GROUPS: SetAsideGroup[] = ['home', 'car', 'kids', 'memberships', 'other'];
const NONE: ReadonlySet<number> = new Set();

/** The POST body a suggestion becomes, as it is (decision B). */
export function bodyFrom(s: SetAsideSuggestion): SetAsideBody {
  return { name: s.name, kind: s.kind, amount_cents: s.amount_cents, due_month: s.due_month, due_day: s.due_day,
    second_month: s.second_month, second_day: s.second_day, due_year: null, account_id: null, payee_key: s.payee_key,
    category: s.category, estimate: null, notes: null };
}

/** Folds every row away, then `done` once (each at once under reduced motion). */
function collapseAll(els: (HTMLElement | null)[], done: () => void) {
  let left = els.length;
  if (left === 0) { done(); return; }
  for (const el of els) collapse(el, () => { left -= 1; if (left === 0) done(); });
}

/** Yearly costs worth setting aside (item 3, P25, P26): one card, a small label per group, nothing ticked. A click
 *  ticks a row and Shift-click a range (lib/selection's picked). The bar adds up the monthly amounts; Set aside makes
 *  them in one write, they fold away, and the toast offers Undo. Viewers read the rows with nothing to tick. */
export function Suggestions({ l, canEdit }: { l: SetAsideList; canEdit: boolean }) {
  const qc = useQueryClient();
  const [picks, setPicks] = useState<ReadonlySet<number>>(NONE);
  const [gone, setGone] = useState<ReadonlySet<number>>(NONE);
  const anchor = useRef<number | null>(null);
  const els = useRef(new Map<number, HTMLElement>());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<{ text: string; token: string } | null>(null);
  // A new list from the server (a refetch, an Undo, a dismissal) starts the picking over: rows are picked by place.
  const [base, setBase] = useState(l.suggestions);
  if (base !== l.suggestions) {
    setBase(l.suggestions);
    setPicks(NONE);
    setGone(NONE);
    anchor.current = null;
  }
  const order = l.suggestions.map((_, i) => i).filter((i) => !gone.has(i));
  const chosen = order.filter((i) => picks.has(i));
  const monthly = chosen.reduce((n, i) => n + l.suggestions[i].monthly_cents, 0);
  const bar = fill(C.PICKED, { n: chosen.length, amount: dollars(monthly) });

  function pick(i: number, range: boolean) {
    const from = range ? anchor.current : null;       // read now: the updater runs after the anchor moves
    setPicks((was) => picked(was, order, i, from));
    anchor.current = i;
    setError(null);
  }
  async function save() {
    if (busy || chosen.length === 0) return;
    setBusy(true);
    setError(null);
    try {
      const r = await addMany(chosen.map((i) => bodyFrom(l.suggestions[i])));
      const text = fill(C.SET_ASIDE_TOAST, { n: chosen.length, amount: dollars(r.monthly_cents) });
      collapseAll(chosen.map((i) => els.current.get(i) ?? null), () => {
        setGone(new Set(chosen));
        setPicks(NONE);
        setToast({ text, token: r.undo });
        void invalidateSetAsides(qc);
      });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function undo() {
    const t = toast?.token;
    setToast(null);
    try { if (t) await undoToken(t); } catch (e) { setError((e as Error).message); }
    await invalidateSetAsides(qc);
  }
  async function run(fn: () => Promise<unknown>) {
    setError(null);
    try { await fn(); } catch (e) { setError((e as Error).message); } finally { await invalidateSetAsides(qc); }
  }
  const onRow = (i: number) => (e: MouseEvent<HTMLElement>) => {
    if ((e.target as HTMLElement).closest('a, button, input')) return;   // the links and the box answer for themselves
    pick(i, e.shiftKey);
  };

  return (
    <section className="card sa-sugg" aria-labelledby="sa-sugg-h" data-testid="sa-suggestions">
      <h2 id="sa-sugg-h">{C.SUGG_HEADING}</h2>
      <p className="small muted">{canEdit ? C.SUGG_NOTE : C.SUGGESTED_NOTE_VIEWER}</p>
      {l.history_months < 12 && <p className="small muted" data-testid="sa-history">{l.history_months === 1 ? C.HISTORY_ONE : fill(C.HISTORY_SHORT, { n: l.history_months })}</p>}
      {l.suggestions.length === 0 && l.dismissed.length === 0 && <p className="muted">{C.NO_SUGGESTIONS}</p>}
      {GROUPS.map((g) => {
        const items = order.filter((i) => l.suggestions[i].group === g);
        if (items.length === 0) return null;
        return (
          <div key={g} className="sa-sugg__group">
            <p className="eyebrow sa-sugg__label">{C.GROUP_LABEL[g]}</p>
            {items.map((i) => {
              const s = l.suggestions[i];
              return (
                <div key={s.key} ref={(el) => { if (el) els.current.set(i, el); else els.current.delete(i); }}
                  className={`sa-pick${picks.has(i) ? ' is-picked' : ''}${canEdit ? ' is-pickable' : ''}`} data-testid="sa-suggestion"
                  onClick={canEdit ? onRow(i) : undefined}>
                  {canEdit && (
                    <input type="checkbox" className="pick-box" checked={picks.has(i)} aria-label={`${s.name}, ${suggestionWhen(s)}`}
                      onClick={(e) => { e.stopPropagation(); }} onChange={(e) => { pick(i, (e.nativeEvent as unknown as globalThis.MouseEvent).shiftKey === true); }} />
                  )}
                  <span className="sa-pick__name">{s.name}</span>
                  <span className="sa-pick__when">{suggestionWhen(s)}</span>
                  {canEdit && (
                    <span className="sa-pick__links">
                      <Link className="link link--quiet" to={suggestionHref(s)} aria-label={fill(C.CHANGE_FIRST_NAMED, { name: s.name })}>{C.CHANGE_FIRST}</Link>
                      {' · '}
                      <button type="button" className="link link--quiet" aria-label={fill(C.NOT_THIS_ONE_NAMED, { name: s.name })}
                        onClick={() => void run(() => dismissSuggestion(s.payee_key, s.category))}>{C.NOT_THIS_ONE}</button>
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        );
      })}
      {l.dismissed.map((d) => (
        <DismissedRow key={d.payee_key + d.category} d={d} canEdit={canEdit} onRestore={() => void run(() => restoreSuggestion(d.payee_key, d.category))} />
      ))}
      {canEdit && chosen.length > 0 && (
        <div className="sa-pickbar" role="region" aria-label={bar}>
          <span>{bar}</span>
          <Button busy={busy} onClick={() => void save()}>{C.SET_ASIDE}</Button>
        </div>
      )}
      {error && <Notice tone="error">{error}</Notice>}
      {toast && <UndoToast text={toast.text} onUndo={() => void undo()} onClose={() => setToast(null)} />}
    </section>
  );
}
