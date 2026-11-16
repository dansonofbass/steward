import { useRef, useState } from 'react';
import { api, patch } from '../../api/client';
import { usePayers } from '../../api/hooks';
import type { IgnoreReply, SnoozeReply, Txn, TxnPatchReply } from '../../api/types';
import { useIsHousehold } from '../../book/BookContext';

export type Verb = 'snooze' | 'ignore';
export type ActKind = 'sort' | Verb;
export type SortDone = { kind: 'sort'; category: string; reply: TxnPatchReply; applied: number; ids: number[] };
export type Done = SortDone | { kind: 'snooze'; reply: SnoozeReply } | { kind: 'ignore'; reply: IgnoreReply };
export type ActionHooks = {
  /** The request is going out: the stack takes a pending entry, focus starts the stamp. */
  onStart?: (kind: ActKind, category: string | null) => void;
  onDone: (d: Done) => void;
  onFail?: (message: string) => void;
};

const messageOf = (err: unknown) => (err instanceof Error ? err.message : 'Something went wrong.');

/** Review focus, Build 3: one card's requests, shared by the list card and the focus card, and the card's local choices:
 *  Business, Reimbursable and who pays (asked once, chosen when there are two or more), and the "Also" box (ticked by
 *  default, sorting-redesign decision 3). The hooks are read at call time, so a reply always reaches the newest ones. */
export function useReviewActions(txn: Txn, hooks: ActionHooks) {
  const household = useIsHousehold();
  const payersQ = usePayers(household);
  const payers = payersQ.data?.payers ?? [];
  const [business, setBusiness] = useState(txn.is_business);
  const [reimb, setReimb] = useState(txn.reimburser_id != null);
  const [payer, setPayer] = useState<number | null>(txn.reimburser_id ?? null);
  const [either, setEither] = useState(false);
  const [pending, setPending] = useState<string | null>(null);
  const [also, setAlso] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [chosen, setChosen] = useState<string | null>(null);
  const h = useRef(hooks);
  h.current = hooks;
  const going = useRef(false);             // a second tap before React re-renders still sends one request
  const matching = txn.matching ?? null;
  const canReimburse = household && !txn.is_transfer
    && (txn.amount_cents < 0 || txn.reimburse_ok === true || txn.reimburser_id != null);
  const payerId = payers.length === 1 ? payers[0].id : payer;
  const asking = payersQ.data !== undefined && (reimb || pending !== null) && payers.length !== 1;

  function toggleReimb() {
    const on = !reimb;
    setReimb(on);
    if (on && business) { setBusiness(false); setEither(true); }
  }

  function toggleBusiness() {
    const on = !business;
    setBusiness(on);
    if (on && reimb) { setReimb(false); setEither(true); }
  }

  function begin(kind: ActKind, category: string | null) {
    going.current = true;
    setBusy(true);
    setError(null);
    h.current.onStart?.(kind, category);
  }

  function fail(err: unknown) {
    const m = messageOf(err);
    setError(m);
    h.current.onFail?.(m);
  }

  function end() { going.current = false; setBusy(false); }

  /** Sorts as `category`. False when it asked for a payer instead (Steward never guesses between payers, choice 20) or
   *  a request is already going. */
  function sort(category: string, picked: number | null = payerId): boolean {
    if (going.current) return false;
    const repaying = category === 'reimbursement';
    if (household && (repaying || reimb) && picked === null) {
      if (repaying) setPending(category);
      return false;
    }
    setPending(null);
    performance.mark('review-tap');
    const body: Record<string, unknown> = { category };
    if (household && business !== txn.is_business) body.is_business = business;
    if (household && !repaying && reimb !== (txn.reimburser_id != null)) body.reimbursable = reimb;
    if (household && (repaying || reimb) && picked !== null && payers.length !== 1) body.reimburser_id = picked;
    if (matching !== null && matching > 0) body.apply_to_matching = also;
    setChosen(category);
    begin('sort', category);
    void api<TxnPatchReply>(`/api/transactions/${txn.id}`, patch(body)).then((r) => {
      performance.mark('review-done');
      performance.measure('review-action', 'review-tap', 'review-done');
      h.current.onDone({ kind: 'sort', category, reply: r, applied: r.result?.applied ?? 0, ids: r.result?.ids ?? [] });
    }).catch((err: unknown) => { setChosen(null); fail(err); }).finally(end);
    return true;
  }

  function post(verb: Verb): boolean {
    if (going.current) return false;
    begin(verb, null);
    void api<SnoozeReply | IgnoreReply>(`/api/review/${txn.id}/${verb}`, { method: 'POST' }).then((r) => {
      h.current.onDone(verb === 'snooze' ? { kind: 'snooze', reply: r as SnoozeReply } : { kind: 'ignore', reply: r as IgnoreReply });
    }).catch(fail).finally(end);
    return true;
  }

  function choosePayer(id: number) {
    setPayer(id);
    if (pending) { const c = pending; setPending(null); sort(c, id); }
  }

  return {
    household, payers, payerId, business, reimb, either, pending, asking, also, setAlso, busy, error, chosen, matching,
    canReimburse, toggleBusiness, toggleReimb, choosePayer, sort, post,
  };
}

export type Actions = ReturnType<typeof useReviewActions>;
