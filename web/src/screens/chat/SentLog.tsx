// Settings → Chat → Everything sent so far (was Sent to Anthropic; spec 4.6; design pass screen 4): who can read it, filters, requests grouped by
// day, and one request opened with when, who asked and approved, the conversation, the four checks the gateway ran and
// exactly what was sent with its aliases decoded. Nothing here can change the log. A Getting ready row records Steward's
// fixed instructions and tools only as their hash; opening it shows their full text with the hash beside it (issue #3).
import { ArrowLeft, Check, ChevronDown, ChevronRight, Cpu, Download, History, MessageSquareText, ScanEye, Store, type LucideIcon } from 'lucide-react';
import { Fragment, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { resolveApiPath } from '../../api/book';
import { useBook, useBookTo, useCanEdit } from '../../book/BookContext';
import { Button } from '../../ui/Button';
import { Card } from '../../ui/Card';
import { Notice } from '../../ui/Notice';
import { Skeleton } from '../../ui/Skeleton';
import { andList, fill } from './askApi';
import { useChatStatus, useInstructions, useSent, useSentDetail, type SentKind, type SentRow } from './api';
import * as C from './copy';
import { gw } from '../../lib/gatewayName';
import './chat.css';

const ICON: Record<SentKind, LucideIcon> = { question: MessageSquareText, results: ScanEye, store_rows: Store, prewarm: Cpu, history: History };
const requestsWord = (n: number) => (n === 1 ? '1 request' : `${n} requests`);

const loggedPrefix = (payload: unknown): string | null => {
  const h = (payload as { prefix_sha256?: unknown } | null)?.prefix_sha256;
  return typeof h === 'string' ? h : null;
};

/** The text a logged prefix_sha256 stands for, fetched once the disclosure opens. */
function FixedInstructions({ payload }: { payload: unknown }) {
  const logged = loggedPrefix(payload);
  const [open, setOpen] = useState(false);
  const q = useInstructions(open);
  const x = q.data?.instructions;
  return (
    <details className="log__fixed" onToggle={(e) => setOpen((e.currentTarget as HTMLDetailsElement).open)}>
      <summary>{C.FIXED_SHOW}</summary>
      {q.isPending && open && <Skeleton lines={3} />}
      {q.isError && <Notice tone="error">{q.error.message}</Notice>}
      {q.isSuccess && !x && <p className="small muted">{gw(C.FIXED_AWAY)}</p>}
      {x && (
        <div className="stack stack--tight">
          <p className="small muted">{fill(x.sha256 === logged ? C.FIXED_SAME : C.FIXED_OTHER, { hash: x.sha256 })}</p>
          <pre className="chat__json">{x.system}</pre>
          <span className="eyebrow">{C.FIXED_TOOLS}</span>
          {x.tools.map((t) => (
            <div key={t.name} className="stack stack--tight">
              <span className="strong">{t.name}</span>
              <p className="small">{t.description}</p>
              <pre className="chat__json">{JSON.stringify(t.input_schema, null, 2)}</pre>
            </div>
          ))}
          <details className="log__fixed">
            <summary>{C.FIXED_HASHED}</summary>
            <pre className="chat__json">{x.hashed}</pre>
          </details>
        </div>
      )}
    </details>
  );
}

function Detail({ sentKey, title }: { sentKey: string; title: string }) {
  const d = useSentDetail(sentKey);
  if (d.isPending) return <div className="log__detail"><Skeleton lines={3} /></div>;
  if (d.isError) return <div className="log__detail"><Notice tone="error">{d.error.message}</Notice></div>;
  const x = d.data;
  const facts: [string, string | null][] = [[C.D_WHEN, x.when], [C.D_WHO, x.who], [C.D_APPROVED, x.approved_by], [C.D_CONVERSATION, x.conversation], [C.D_SIZE, x.size]];
  return (
    <section className="log__detail" aria-label={title}>
      <dl className="log__facts">{facts.filter(([, v]) => v).map(([k, v]) => <Fragment key={k}><dt>{k}</dt><dd>{v}</dd></Fragment>)}</dl>
      <span className="eyebrow">{gw(C.CHECKS_TITLE)}</span>
      <ul className="checks">{x.checks.map((c) => <li key={c}><Check size={20} aria-hidden="true" />{c}</li>)}</ul>
      <span className="eyebrow">{C.EXACT_TITLE}</span>
      {x.parts.map((p) => (
        <div key={p.id} className="stack stack--tight">
          <span className="small muted">{p.label} · {fill(C.FINGERPRINT, { hash: p.sha256.slice(0, 12) })}</span>
          <pre className="chat__json">{JSON.stringify(p.payload, null, 2)}</pre>
          {loggedPrefix(p.payload) !== null && <FixedInstructions payload={p.payload} />}
        </div>
      ))}
      {x.aliases.length > 0 && <ul className="plain small">{x.aliases.map((a) => <li key={a.alias}>{fill(C.ALIAS_IS, a)}</li>)}</ul>}
    </section>
  );
}

export function SentLog() {
  const book = useBook();
  const to = useBookTo();
  const canEdit = useCanEdit();
  const [params] = useSearchParams();
  const status = useChatStatus();
  const [who, setWho] = useState<number | null>(null);
  const [what, setWhat] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(params.get('open'));
  const sent = useSent({ who, what });
  const rows: SentRow[] = sent.data?.pages.flatMap((p) => p.requests) ?? [];
  const people = sent.data?.pages[0]?.people ?? [];
  const days = rows.reduce<{ day: string; rows: SentRow[] }[]>((acc, r) => {
    const last = acc[acc.length - 1];
    if (last && last.day === r.day) last.rows.push(r); else acc.push({ day: r.day, rows: [r] });
    return acc;
  }, []);
  const openRow = rows.find((r) => r.key === open);
  return (
    <section className="spage chat" aria-labelledby="sent-h">
      {/* A viewer has no Settings → Chat; they came here from Ask. */}
      {canEdit
        ? <Link className="link" to={to('/settings/chat')}><ArrowLeft size={20} aria-hidden="true" />{C.BACK_TO_CHAT}</Link>
        : <Link className="link" to={to('/ask')}><ArrowLeft size={20} aria-hidden="true" />{C.BACK_TO_ASK}</Link>}
      <h2 id="sent-h">{C.SENT}</h2>
      {status.data && <p className="muted">{fill(C.LOG_LEDE, { book: book?.name ?? '', names: andList(status.data.members) })}</p>}
      <div className="log__filters">
        <label className="field"><span className="field__label">{C.WHO}</span>
          <select aria-label={C.WHO} value={who ?? ''} onChange={(e) => setWho(e.target.value ? Number(e.target.value) : null)}>
            <option value="">{C.EVERYONE}</option>
            {people.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </label>
        <label className="field"><span className="field__label">{C.WHAT}</span>
          <select aria-label={C.WHAT} value={what ?? ''} onChange={(e) => setWhat(e.target.value || null)}>
            <option value="">{C.EVERYTHING}</option>
            {Object.entries(C.WHAT_OPTIONS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
        {status.data?.can_change && (
          <a className="chat__download" href={resolveApiPath('/api/chat/export')} download><Download size={20} aria-hidden="true" />{C.DOWNLOAD}</a>
        )}
      </div>
      {open && !openRow && <Card><Detail sentKey={open} title={open} /></Card>}
      {sent.isPending && <Card><Skeleton lines={4} /></Card>}
      {sent.isError && <Notice tone="error">{sent.error.message}</Notice>}
      {sent.isSuccess && rows.length === 0 && <Card className="line line--empty">{C.NOTHING_SENT}</Card>}
      {days.length > 0 && (
        <Card className="log">
          {days.map((d) => (
            <div key={d.day}>
              <div className="log__day">{fill(C.DAY_HEAD, { day: d.day, n: requestsWord(d.rows.length) })}</div>
              {d.rows.map((r) => {
                const Icon = ICON[r.kind] ?? History;
                const isOpen = open === r.key;
                return (
                  <Fragment key={r.key}>
                    <button type="button" className={`log__row${isOpen ? ' is-open' : ''}`} aria-expanded={isOpen} onClick={() => setOpen(isOpen ? null : r.key)}>
                      <Icon size={20} aria-hidden="true" />
                      <span className="stack stack--tight">
                        <span className="log__what">{r.what}</span>
                        <span className="log__meta"><span>{r.when}</span><span>{r.who}</span><span>{r.channel}</span>{r.conversation && <span>{r.conversation}</span>}</span>
                      </span>
                      <span className="log__size">{r.size}{isOpen ? <ChevronDown size={20} aria-hidden="true" /> : <ChevronRight size={20} aria-hidden="true" />}</span>
                    </button>
                    {isOpen && <Detail sentKey={r.key} title={r.what} />}
                  </Fragment>
                );
              })}
            </div>
          ))}
        </Card>
      )}
      {sent.hasNextPage && <Button variant="quiet" busy={sent.isFetchingNextPage} onClick={() => void sent.fetchNextPage()}>{C.SHOW_MORE}</Button>}
    </section>
  );
}
