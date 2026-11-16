import { useQueryClient } from '@tanstack/react-query';
import { Banknote, ChevronRight, CircleCheck, Flag, Mail, MailWarning, MailX, Send, TrendingDown, UserCheck } from 'lucide-react';
import { useRef, useState } from 'react';
import { useParams } from 'react-router-dom';
import { useBook } from '../../book/BookContext';
import { Link } from '../../book/links';
import { TRY_AGAIN } from '../../lib/copy';
import { money } from '../../lib/format';
import { composing } from '../../lib/ime';
import { Button } from '../../ui/Button';
import { Card } from '../../ui/Card';
import { MoneyInput } from '../../ui/MoneyInput';
import { Notice } from '../../ui/Notice';
import { Skeleton } from '../../ui/Skeleton';
import { fill, parentName, possessive } from '../inventory/format';
import '../inventory/inventory.css';
import { dollarsText, toHundredths } from '../settings/money';
import { failure } from '../settings/shared';
import { refreshFlags, sendTestEmail, setCashFloor, setEmails, setFloor, setLarge, stopMyEmails, useWatching, type Person, type WatchSettings } from './api';
import * as C from './copy';
import { KnownPayees } from './KnownPayees';
import './watching.css';

/** Settings → Watching (README screen 5); /settings/watching/known is Known payees (README screen 4). */
export function Watching() {
  const { step } = useParams();
  return step === 'known' ? <KnownPayees /> : <WatchingMain />;
}

function Switch({ on, label, disabled, onToggle }: { on: boolean; label: string; disabled: boolean; onToggle: () => void }) {
  return <button type="button" role="switch" aria-checked={on} aria-label={label} className={`switch${on ? ' is-on' : ''}`} disabled={disabled} onClick={onToggle} />;
}

function WatchingMain() {
  const q = useWatching();
  const qc = useQueryClient();
  const names = possessive(parentName(useBook()));
  const [large, setLargeText] = useState<string | null>(null);
  const [cashFloor, setCashFloorText] = useState<string | null>(null);
  const [floors, setFloors] = useState<Record<number, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const savingFloors = useRef(new Set<number>());   // Enter and then the blur must not save one floor twice
  if (q.isPending) return <Card><Skeleton lines={6} /></Card>;
  if (q.isError) return <Notice tone="error"><p>{q.error.message}</p><Button variant="quiet" onClick={() => q.refetch()}>{TRY_AGAIN}</Button></Notice>;
  const s = q.data;
  const edit = s.can_edit;

  /** Runs a save. True when it worked, so typed text is only cleared after a save that took. */
  async function act(fn: () => Promise<WatchSettings | unknown>): Promise<boolean> {
    setBusy(true);
    setError(null);
    try {
      const out = await fn();
      if (out && typeof out === 'object' && 'people' in out) qc.setQueryData(['watching'], out);
      await refreshFlags(qc);
      return true;
    } catch (e) {
      setError(failure(e));
      return false;
    } finally {
      setBusy(false);
    }
  }
  function saveLarge() {
    const p = toHundredths(large ?? '');
    if ('error' in p) { setError(p.error); return; }
    const sentText = large;
    void act(() => setLarge(p.value)).then((ok) => { if (ok) setLargeText((now) => (now === sentText ? null : now)); });
  }
  function saveCashFloor() {
    const p = toHundredths(cashFloor ?? '');
    if ('error' in p) { setError(p.error); return; }
    const sentText = cashFloor;
    void act(() => setCashFloor(p.value)).then((ok) => { if (ok) setCashFloorText((now) => (now === sentText ? null : now)); });
  }
  function saveFloor(itemId: number, current: number | null) {
    const raw = floors[itemId];
    if (raw === undefined) return;
    const text = raw.trim();
    let cents: number | null = null;
    if (text) {
      const p = toHundredths(text);
      if ('error' in p) { setError(p.error); return; }
      cents = p.value;
    }
    if (cents === current || savingFloors.current.has(itemId)) return;
    savingFloors.current.add(itemId);
    void act(() => setFloor(itemId, cents)).then((ok) => {
      savingFloors.current.delete(itemId);
      // Clear only if nothing was typed since: a second edit made during the save stays.
      if (ok) setFloors((f) => {
        if (f[itemId] !== raw) return f;
        const n = { ...f };
        delete n[itemId];
        return n;
      });
    });
  }
  const toggle = (p: Person, key: 'urgent' | 'summary') => void act(() => setEmails(p.user_id, { [key]: !p[key] }));
  const me = s.people.find((p) => p.is_me);
  const known = s.known.length === 1 ? C.ONE_KNOWN : fill(C.N_KNOWN, { n: s.known.length });

  return (
    <section className="stack watching" aria-label={C.WATCHING}>
      <div className="page-head">
        <h2 className="subhead with-icon"><Flag size={20} aria-hidden="true" />{C.WATCHING}</h2>
        <p className="muted">{fill(C.WATCHING_LEDE, { names })}</p>
      </div>
      {error && <Notice tone="error">{error}</Notice>}
      <div className="set-cols">
        <div className="stack set-col">
          <section className="set-sec" aria-label={C.LARGE_AMOUNT}>
            <h3><Banknote size={20} aria-hidden="true" />{C.LARGE_AMOUNT}</h3>
            <div className="card stack stack--tight">
              <div className="row-actions large-row">
                <div className="field large-in">
                  <label className="field__label" htmlFor="watch-large">{C.FLAG_MONEY_OUT}</label>
                  <MoneyInput id="watch-large" value={large ?? dollarsText(s.large_cents)} disabled={!edit} onValueChange={setLargeText} />
                </div>
                {edit && large !== null && <Button busy={busy} onClick={saveLarge}>{C.SAVE}</Button>}
              </div>
              <p className="small muted">{fill(C.LARGE_HINT, { amount: money(s.default_cents) })}</p>
              <div className="row-actions large-row">
                <div className="field large-in">
                  <label className="field__label" htmlFor="watch-cash-floor">{C.CASH_FLOOR}</label>
                  <MoneyInput id="watch-cash-floor" value={cashFloor ?? dollarsText(s.cash_alert_floor_cents)} disabled={!edit} onValueChange={setCashFloorText} />
                </div>
                {edit && cashFloor !== null && <Button busy={busy} onClick={saveCashFloor}>{C.SAVE}</Button>}
              </div>
              <p className="small muted">{fill(C.CASH_FLOOR_HINT, { amount: money(s.default_cash_floor_cents) })}</p>
            </div>
          </section>

          <section className="set-sec" aria-label={C.FLOORS}>
            <h3><TrendingDown size={20} aria-hidden="true" />{C.FLOORS}</h3>
            <div className="card set-rows">
              {s.floors.map((f) => (
                <div key={f.item_id} className="set-row">
                  <span className="stack stack--tight">
                    <span className="strong">{f.name}</span>
                    <span className="set-row__sub">{f.sub}{f.under && <> · <span className="warn strong">{C.UNDER_FLOOR}</span></>}</span>
                  </span>
                  <div className="floor-in">
                    <MoneyInput aria-label={fill(C.FLOOR_FOR, { name: f.name })} placeholder={C.NO_FLOOR} disabled={!edit}
                      value={floors[f.item_id] ?? (f.floor_cents !== null ? dollarsText(f.floor_cents) : '')}
                      onValueChange={(v) => setFloors((all) => ({ ...all, [f.item_id]: v }))}
                      onBlur={() => saveFloor(f.item_id, f.floor_cents)}
                      onKeyDown={(e) => { if (e.key === 'Enter' && !composing(e)) saveFloor(f.item_id, f.floor_cents); }} />
                  </div>
                </div>
              ))}
            </div>
            <p className="small muted">{C.FLOORS_FOOT}</p>
          </section>

          <section className="set-sec" aria-label={C.KNOWN_PAYEES}>
            <h3><UserCheck size={20} aria-hidden="true" />{C.KNOWN_PAYEES}</h3>
            <Link className="card attn plain-link" to="/settings/watching/known">
              <span className="attn__main"><span><strong>{known}</strong> <span className="muted">· {C.KNOWN_SUB}</span></span></span>
              <ChevronRight size={20} aria-hidden="true" />
            </Link>
          </section>
        </div>

        <div className="stack set-col">
          <section className="set-sec" aria-label={C.EMAIL}>
            <h3><Mail size={20} aria-hidden="true" />{C.EMAIL}</h3>
            {s.mail.ready ? (
              <Notice>
                <span className="stack stack--tight">
                  <span><CircleCheck size={20} aria-hidden="true" className="ok-mark" /> <strong>{C.EMAIL_SET_UP}</strong> {s.mail.last_sent ?? C.NOTHING_SENT}</span>
                  {edit && <span className="row-actions"><Button variant="quiet" icon={Send} busy={busy} onClick={() => void act(async () => setSent((await sendTestEmail()).sent_to))}>{C.SEND_TEST}</Button></span>}
                  {sent && <span className="small muted">{fill(C.TEST_SENT, { email: sent })}</span>}
                </span>
              </Notice>
            ) : (
              <Notice tone="warn">
                <span className="stack stack--tight">
                  <span><MailX size={20} aria-hidden="true" /> <strong>{C.EMAIL_NOT_SET_UP}</strong> {C.EMAIL_NOT_SET_UP_BODY}</span>
                  {edit && <span className="small muted">{C.EMAIL_HOW}</span>}
                </span>
              </Notice>
            )}
            {s.mail.failure && (
              <Notice tone="error">
                <span className="stack stack--tight">
                  <span><MailWarning size={20} aria-hidden="true" /> <strong>{s.mail.failure.title}</strong> {s.mail.failure.line}</span>
                  <span className="small muted">{C.FAILURE_FOOT}</span>
                </span>
              </Notice>
            )}
            <div className="card who-card">
              <div className="who who--head"><span>{C.WHO_GETS}</span><span>{C.URGENT_RIGHT_AWAY}</span><span>{C.DAILY_SUMMARY}</span></div>
              {s.people.map((p) => (
                <div key={p.user_id} className="who">
                  <span className="stack stack--tight"><span className="strong">{p.name}</span><span className="set-row__sub">{p.role_label}</span></span>
                  <span><Switch on={p.urgent} label={fill(C.URGENT_FOR, { name: p.name })} disabled={!p.can_change || busy} onToggle={() => toggle(p, 'urgent')} /></span>
                  <span><Switch on={p.summary} label={fill(C.SUMMARY_FOR, { name: p.name })} disabled={!p.can_change || busy} onToggle={() => toggle(p, 'summary')} /></span>
                </div>
              ))}
            </div>
            {!edit && me && (me.urgent || me.summary) && (
              <div className="row-actions"><Button variant="quiet" busy={busy} onClick={() => void act(() => stopMyEmails())}>{C.STOP_MY_EMAILS}</Button></div>
            )}
            <ul className="act-help">
              {C.EMAIL_HELP.map(([lead, text]) => <li key={text}>{lead && <b>{lead}</b>} {text}</li>)}
            </ul>
          </section>
        </div>
      </div>
    </section>
  );
}

export default Watching;
