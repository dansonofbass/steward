import { useQueryClient } from '@tanstack/react-query';
import { ChevronRight, Cpu, Gauge, LockKeyhole, MessagesSquare, Power, ScanEye, Terminal } from 'lucide-react';
import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { currentBook } from '../../api/book';
import { useMe } from '../../api/hooks';
import type { BookSummary } from '../../api/types';
import { bookHref, useBook } from '../../book/BookContext';
import { HOUSEHOLD_KIND, PARENT_KIND, TRY_AGAIN } from '../../lib/copy';
import { money } from '../../lib/format';
import { setQueryDataIfStillIn } from '../../queryClient';
import { Button } from '../../ui/Button';
import { Card } from '../../ui/Card';
import { CheckLine, type CheckWords } from '../../ui/CheckLine';
import { Notice } from '../../ui/Notice';
import { Sheet } from '../../ui/Sheet';
import { Skeleton } from '../../ui/Skeleton';
import { failure } from '../settings/shared';
import { andList, fill } from './askApi';
import { setBudget, setChatOnIn, useBookStatus, useChatStatus, useUsage, type ChatStatus, type Usage } from './api';
import * as C from './copy';
import { gw } from '../../lib/gatewayName';
import { PairForm } from '../ready/PairForm';
import { ClaudeCodeCard } from './ClaudeCode';
import { SentLog } from './SentLog';
import { thisMonth } from './states';
import './chat.css';

const requestsWord = (n: number) => (n === 1 ? '1 request' : `${n} requests`);
const dollars = (cents: number) => money(cents).replace(/\.00$/, '');

type Split = NonNullable<Usage['usage']>;

/** Each book's row, then its people under it. A name that appears in more than one book carries its book, so two
 *  rows for "JR" aren't left to guess (final review, Task 17). */
function splitRows(u: Split) {
  const count = new Map<string, number>();
  u.by_person.forEach((p) => count.set(p.person, (count.get(p.person) ?? 0) + 1));
  const person = (p: Split['by_person'][number]) => ({
    key: `p-${p.book}-${p.person}`, person: true, questions: p.questions, spent: p.spent,
    label: (count.get(p.person) ?? 0) > 1 ? `${p.person} · ${p.book}` : p.person });
  const books = new Set(u.by_book.map((b) => b.book));
  return [
    ...u.by_book.flatMap((b) => [{ key: `b-${b.book}`, person: false, label: b.book, questions: b.questions, spent: b.spent },
      ...u.by_person.filter((p) => p.book === b.book).map(person)]),
    ...u.by_person.filter((p) => !books.has(p.book)).map(person),
  ];
}

function people(s: ChatStatus): string {
  const viewers = s.members.filter((n) => !s.managers.includes(n));
  return [s.managers.length ? `${andList(s.managers)}, ${s.managers.length === 1 ? 'manager' : 'managers'}` : '',
    viewers.length ? `${andList(viewers)}, ${viewers.length === 1 ? 'viewer' : 'viewers'}` : ''].filter(Boolean).join('; ');
}

function GatewayCheck({ s }: { s: ChatStatus }) {
  const g = s.gateway;
  const book = useBook();
  const ok = g.state === 'ok';
  // Once a code has been taken here, the form (and the server's line under it) stays up after the status flips to paired.
  const [justPaired, setJustPaired] = useState(false);
  const [before, after] = gw(C.GATEWAY_CHECKED).split('{command}').map((half) => fill(half, { when: g.checked ?? '' }));
  const checks: [boolean, CheckWords][] = g.checks ? [[g.checks.redaction, C.CHECK_REDACTION], [g.checks.key, C.CHECK_KEY], [g.checks.categorizer, C.CHECK_CATEGORIZER]] : [];
  return (
    <section className="set-sec" aria-labelledby="pc-h">
      <h3 id="pc-h" className="chat__sub"><Cpu size={20} aria-hidden="true" />{gw(C.GATEWAY)}</h3>
      <Card className="stack stack--tight">
        <p className="chat__state"><span className={`chat-dot${ok ? '' : ' chat-dot--off'}`} aria-hidden="true" />{ok ? gw(C.GATEWAY_OK) : g.state === 'away' ? gw(C.GATEWAY_AWAY) : g.line}</p>
        {(justPaired || !g.paired) && g.url_set && book?.kind === 'household' && book.role === 'manager' && <PairForm onPaired={() => setJustPaired(true)} />}
        {checks.length > 0 && (
          <ul className="checks">{checks.map(([on, words]) => <CheckLine key={words[0]} ok={on} words={words} />)}</ul>
        )}
        {g.pdf_place && <p className="small muted">{g.pdf_place === 'gateway' ? gw(C.PDF_ON_GATEWAY) : C.PDF_ON_STEWARD}</p>}
        {ok && g.checked && <p className="small muted">{before}<code className="raw">{C.STOP_COMMAND}</code>{after}</p>}
        {!ok && <p className="small muted">{g.last_answered ? fill(C.GATEWAY_AWAY_NOTE, { when: g.last_answered }) : C.GATEWAY_NEVER}</p>}
      </Card>
    </section>
  );
}

function BookRow({ book }: { book: BookSummary }) {
  const q = useBookStatus(book.slug);
  const qc = useQueryClient();
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (q.isPending) return <div className="chat-set-row"><Skeleton lines={1} /></div>;
  if (q.isError) return <div className="chat-set-row"><Notice tone="error">{q.error.message}</Notice></div>;
  const s = q.data;
  const title = fill(C.CHAT_IN, { book: book.name });
  const viewers = s.members.filter((n) => !s.managers.includes(n));
  // Who sees the disclosure later: the others, since the manager reading it now has (INS-18), "each" only for two or more.
  const others = s.others ?? s.members;
  const note = [others.length > 0 && fill(others.length === 1 ? C.TURN_ON_NOTE_ONE : C.TURN_ON_NOTE, { names: andList(others) }),
    viewers.length > 0 && fill(C.TURN_ON_VIEWERS, { viewers: andList(viewers) })].filter(Boolean).join(' ');
  async function turn(on: boolean) {
    setBusy(true);
    setError(null);
    const bookAtStart = currentBook();
    try {
      const r = await setChatOnIn(book.slug, on);
      setQueryDataIfStillIn<ChatStatus>(qc, bookAtStart, ['chat', 'status-of', book.slug], () => r);
      if (book.slug === bookAtStart) setQueryDataIfStillIn<ChatStatus>(qc, bookAtStart, ['chat', 'status'], () => r);
      void qc.invalidateQueries({ queryKey: ['me'] });          // the Ask button follows (plan B ruling 26)
      setAsking(false);
    } catch (e) {
      setError(failure(e));
    } finally {
      setBusy(false);
    }
  }
  const sub = [book.kind === 'household' ? HOUSEHOLD_KIND : PARENT_KIND, people(s), s.changed?.line].filter(Boolean).join(' · ');
  return (
    <div className="chat-set-row">
      <span className="stack stack--tight"><span className="strong">{book.name}</span><span className="set-row__sub">{sub}</span></span>
      {s.can_change
        ? <button type="button" role="switch" aria-checked={s.on} aria-label={title} className={`switch${s.on ? ' is-on' : ''}`}
            disabled={busy} onClick={() => (s.on ? void turn(false) : setAsking(true))} />
        : <span className="small strong">{s.on ? C.ON : C.OFF}</span>}
      {error && <Notice tone="error">{error}</Notice>}
      <Sheet open={asking} onClose={() => setAsking(false)} title={fill(C.TURN_ON_IN, { book: book.name })}>
        <div className="sheet-form">
          <p>{s.disclosure}</p>
          {note && <p className="small muted">{note}</p>}
          <div className="row-actions">
            <Button icon={Power} busy={busy} onClick={() => void turn(true)}>{C.TURN_ON}</Button>
            <Button variant="quiet" onClick={() => setAsking(false)}>{C.CANCEL}</Button>
          </div>
        </div>
      </Sheet>
    </div>
  );
}

function SentLink({ book }: { book: BookSummary }) {
  const q = useBookStatus(book.slug);
  if (!q.data) return null;
  const sm = q.data.sent_month;
  return (
    <Link className="chat-set-row chat__sentlink" to={bookHref(book.slug, '/settings/chat/sent')}>
      <span><strong>{fill(C.SENT_ROW, { book: book.name, n: requestsWord(sm.requests) })}</strong>{sm.last && <span className="muted"> · {fill(C.SENT_LAST, { when: sm.last })}</span>}</span>
      <ChevronRight size={20} aria-hidden="true" />
    </Link>
  );
}

function Budget({ s }: { s: ChatStatus }) {
  const qc = useQueryClient();
  const usage = useUsage();
  const b = s.budget;
  const [cap, setCap] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const u = usage.data?.usage ?? null;
  if (!b) {
    return <section className="set-sec"><h3 className="chat__sub"><Gauge size={20} aria-hidden="true" />{C.BUDGET_TITLE}</h3><Card>{gw(C.NO_BUDGET)}</Card></section>;
  }
  const pct = Math.min(100, Math.round((b.spent_cents / b.cap_cents) * 100));
  const month = thisMonth();
  const pace = b.spent_cents > 0 ? Math.round((b.spent_cents / month.day) * month.days) : 0;
  async function save() {
    const value = Number((cap ?? String(b!.cap_cents / 100)).trim());
    setSaved(false);
    if (!Number.isInteger(value) || value < 1 || value > 100) { setError(C.BUDGET_HELP); return; }
    setBusy(true);
    setError(null);
    try {
      await setBudget({ cap_dollars: value, model: b!.model });
      setSaved(true);
      void qc.invalidateQueries({ queryKey: ['chat'] });
    } catch (e) {
      setError(failure(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="set-sec" aria-labelledby="bu-h">
      <h3 id="bu-h" className="chat__sub"><Gauge size={20} aria-hidden="true" />{C.BUDGET_TITLE}</h3>
      <Card className="stack">
        <p>{b.line}</p>
        <div className={`meter${b.cap_line ? ' meter--full' : b.warn ? ' meter--warn' : ''}`} role="img" aria-label={fill(C.METER_LABEL, { pct })}><span style={{ width: `${pct}%` }} /></div>
        {pace > 0 && <p className="small muted">{fill(C.PACE, { month: month.name, amount: money(pace), cap: dollars(b.cap_cents) })}</p>}
        {b.warn && <Notice tone="warn">{b.warn}</Notice>}
        {b.cap_line && <Notice tone="warn">{b.cap_line}</Notice>}
        {s.can_budget && (
          <form className="chat__budget" onSubmit={(e) => { e.preventDefault(); void save(); }}>
            <label className="field"><span className="field__label">{C.BUDGET_FIELD}</span>
              <input inputMode="numeric" aria-label={C.BUDGET_FIELD} value={cap ?? String(b.cap_cents / 100)} onChange={(e) => setCap(e.target.value)} />
            </label>
            <Button type="submit" variant="quiet" busy={busy}>{C.SAVE}</Button>
          </form>
        )}
        {error && <Notice tone="error">{error}</Notice>}
        {saved && <p className="small">{C.SAVED}</p>}
        <p className="small muted">{C.BUDGET_KEY_NOTE}</p>
        {u && (u.by_book.length > 0 || u.by_person.length > 0) && (
          <table className="split-table">
            <thead><tr><th>{C.COL_THIS_MONTH}</th><th>{C.COL_QUESTIONS}</th><th>{C.COL_COST}</th></tr></thead>
            <tbody>
              {splitRows(u).map((x) => <tr key={x.key}><td className={x.person ? 'muted' : undefined}>{x.label}</td><td>{x.questions}</td><td>{x.spent}</td></tr>)}
            </tbody>
          </table>
        )}
        {u && u.months.length > 1 && (
          <ul className="plain chat__usage">{u.months.slice(1).map((m) => <li key={m.month}><span>{m.month}</span><span>{m.spent} · {m.questions === 1 ? C.ONE_QUESTION : fill(C.N_QUESTIONS, { n: m.questions })}</span></li>)}</ul>
        )}
        {u && u.months.length <= 1 && <p className="small muted">{C.EARLIER_MONTHS}</p>}
      </Card>
    </section>
  );
}

function Model({ s, household }: { s: ChatStatus; household: string }) {
  const qc = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const b = s.budget;
  if (!b) return null;
  async function pick(model: string) {
    setError(null);
    try {
      await setBudget({ cap_dollars: b!.cap_cents / 100, model });
      void qc.invalidateQueries({ queryKey: ['chat'] });
    } catch (e) {
      setError(failure(e));
    }
  }
  return (
    <section className="set-sec" aria-labelledby="md-h">
      <h3 id="md-h" className="chat__sub"><ScanEye size={20} aria-hidden="true" />{C.MODEL_TITLE}</h3>
      <Card className="chat__models">
        {s.models.map((m) => {
          const info = C.MODEL_INFO[m.id] ?? { name: m.label, about: '' };
          return s.can_budget ? (
            <label key={m.id} className="model-opt">
              <input type="radio" name="model" checked={b.model === m.id} onChange={() => void pick(m.id)} aria-label={info.name} />
              <span className="stack stack--tight"><span className="strong">{info.name}</span><span className="small muted">{info.about}</span></span>
            </label>
          ) : b.model === m.id ? (
            <div key={m.id} className="model-opt"><span className="stack stack--tight"><span className="strong">{info.name}</span><span className="small muted">{info.about}</span></span></div>
          ) : null;
        })}
      </Card>
      {error && <Notice tone="error">{error}</Notice>}
      <p className="small muted">{fill(C.MODEL_NOTE, { household })}</p>
    </section>
  );
}

function Overview() {
  const q = useChatStatus();
  const me = useMe();
  const book = useBook();
  if (q.isPending) return <Card><Skeleton lines={5} /></Card>;
  if (q.isError) return <Notice tone="error"><p>{q.error.message}</p><Button variant="quiet" onClick={() => q.refetch()}>{TRY_AGAIN}</Button></Notice>;
  const s = q.data;
  const books = (me.data?.books ?? []).filter((b) => b.available);
  const list = books.length > 0 ? books : book ? [book] : [];
  const household = list.find((b) => b.kind === 'household')?.name ?? 'the household book';
  return (
    <section className="spage chat" aria-labelledby="chat-h">
      <h2 id="chat-h" className="chat__sub"><MessagesSquare size={20} aria-hidden="true" />{C.CHAT}</h2>
      <p className="muted">{C.SETTINGS_LEDE}</p>
      <div className="chat__cols">
        <div className="stack">
          <GatewayCheck s={s} />
          <section className="set-sec" aria-labelledby="bk-h">
            <h3 id="bk-h" className="chat__sub"><Power size={20} aria-hidden="true" />{C.BOOKS_TITLE}</h3>
            <Card className="chat-set-rows">{list.map((b) => <BookRow key={b.slug} book={b} />)}</Card>
            <p className="small muted">{C.BOOKS_NOTE}</p>
          </section>
          <section className="set-sec" aria-labelledby="lg-h">
            <h3 id="lg-h" className="chat__sub"><LockKeyhole size={20} aria-hidden="true" />{C.SENT}</h3>
            <Card className="chat-set-rows">{list.map((b) => <SentLink key={b.slug} book={b} />)}</Card>
            <p className="small muted">{C.SENT_NOTE}</p>
          </section>
          {s.gateway.mcp !== false && (
            <section className="set-sec" aria-labelledby="cc-h">
              <h3 id="cc-h" className="chat__sub"><Terminal size={20} aria-hidden="true" />{C.CC_TITLE}</h3>
              <Card className="chat-set-rows">{list.map((b) => <ClaudeCodeCard key={b.slug} book={b} />)}</Card>
              <p className="small muted">{gw(C.CC_NOTE)}</p>
            </section>
          )}
        </div>
        <div className="stack">
          <Budget s={s} />
          <Model s={s} household={household} />
        </div>
      </div>
    </section>
  );
}

export default function ChatSettings() {
  const { step } = useParams();
  return step === 'sent' ? <SentLog /> : <Overview />;
}
