// The Ask page (spec 5; phase 10 decision 3): a tab page like the others, in the main column with the tabs showing.
// Head: "Ask about {book}" with History and New beside it (web/mockups/nav-ask.html); the line about what stays in
// Steward, with What's sent. Body: the disclosure once per person per book, the off, away, paused and used-up states
// (states.tsx, shared with Ask about this's panel), the empty page with fixed examples (JR decision 8), a
// conversation, or History. Foot: the chip from ?about= (P25) with ✕ and add back, and the composer, whose What Claude
// will see shows the about line and replays the first-use tip (P23). Open in Ask's draft arrives in the router's state.
import { ArrowLeft, Eye, Gauge, History as HistoryIcon, LockKeyhole, MessageCircleQuestionMark, SquarePen } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { Link, useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { useMe } from '../../api/hooks';
import type { BookSummary } from '../../api/types';
import { parseAboutParam } from '../../ask/about';
import { bookHref, useBook } from '../../book/BookContext';
import { TRY_AGAIN } from '../../lib/copy';
import { Button } from '../../ui/Button';
import { Notice } from '../../ui/Notice';
import { Skeleton } from '../../ui/Skeleton';
import { AboutChip } from './AboutChip';
import { useChatStatus } from './api';
import { fill, prewarm } from './askApi';
import { Composer } from './Composer';
import { Conversation } from './Conversation';
import * as C from './copy';
import { gw } from '../../lib/gatewayName';
import { History } from './History';
import { CapState, Disclosure, GatewayState, nextMonth, OffState } from './states';
import { useAboutReply } from './useAboutReply';
import { useAsk } from './useAsk';
import { useAskTour } from './useAskTour';
import './ask.css';

const parentName = (b: BookSummary) => (b.owners.find((o) => o.key !== 'joint' && o.key !== 'business')?.label ?? b.name)
  .replace(/\s*\(.*\)\s*$/, '');

function Head({ book, view, viewer, warn, onHistory, onBack, onNew }: {
  book: BookSummary; view: 'ask' | 'history'; viewer: boolean; warn: string | null; onHistory: () => void; onBack: () => void;
  onNew: () => void;
}) {
  return (
    <header className="askp__head">
      <div className="askp__bar">
        <h1 className="askp__title" tabIndex={-1}>{view === 'history' ? C.HISTORY_TITLE : fill(C.ASK_TITLE, { book: book.name })}</h1>
        <span className="row-actions">
          {view === 'history'
            ? <button type="button" className="link" onClick={onBack}><ArrowLeft size={20} aria-hidden="true" />{C.BACK_TO_QUESTION}</button>
            : <>
                <button type="button" className="link" onClick={onHistory}><HistoryIcon size={20} aria-hidden="true" />{C.HISTORY}</button>
                <button type="button" className="link" onClick={onNew}><SquarePen size={20} aria-hidden="true" />{C.NEW}</button>
              </>}
        </span>
      </div>
      <p className="askp__sub">
        {view === 'history' ? <span>{fill(C.HISTORY_SUB, { book: book.name })}</span> : <>
          <span>{C.LEDE}</span>
          <Link className="link" to={bookHref(book.slug, '/settings/chat/sent')}><LockKeyhole size={20} aria-hidden="true" />{C.WHATS_SENT}</Link>
        </>}
      </p>
      {viewer && <p className="viewer-tag"><Eye size={20} aria-hidden="true" />{C.VIEWER_TAG}</p>}
      {warn && <p className="budget-line"><Gauge size={20} aria-hidden="true" />{warn}</p>}
    </header>
  );
}

export default function Ask() {
  const book = useBook() as BookSummary;
  const sample = book.sample === true;
  const status = useChatStatus(!sample);   // a Sample asks the chat API nothing
  const me = useMe();
  const nav = useNavigate();
  const loc = useLocation();
  const [search, setSearch] = useSearchParams();
  const { '*': rest = '' } = useParams();
  const go = (path: string, replace = false) => nav(bookHref(book.slug, path), { replace });
  const view: 'ask' | 'history' = rest === 'history' ? 'history' : 'ask';
  const match = /^c\/(\d+)$/.exec(rest);
  const cid = match ? Number(match[1]) : null;
  const sentDraft = (loc.state as { draft?: unknown } | null)?.draft;
  const [draft, setDraft] = useState(typeof sentDraft === 'string' ? sentDraft : '');
  // ?about= (P25): ✕ drops it from the address and add back puts it there again (Engineering choice 16).
  const param = search.get('about');
  const [last, setLast] = useState<string | null>(param);
  useEffect(() => { if (param !== null) setLast(param); }, [param]);
  const aboutIn = parseAboutParam(param ?? last);
  const removed = param === null && last !== null;
  const [nonce, setNonce] = useState(0);
  const about = useAboutReply(sample ? null : aboutIn, nonce);
  const chip = !removed && about.status === 'ready' ? about.reply : null;
  const keep = param !== null && parseAboutParam(param) ? `?about=${param}` : '';
  const asking = useAsk(cid, (id) => go(`/ask/c/${id}${keep}`, true));
  const panel = useRef<HTMLElement>(null);
  const focused = useRef(false);
  const st = status.data;
  const seen = !!st && st.on && st.seen;
  const blockedNow = seen && st.gateway.state !== 'ok';
  const cappedNow = seen && !!st.budget?.cap_line;
  const tour = useAskTour(me.data?.user.id ?? null,
    view === 'ask' && seen && (chip !== null || (draft.trim() !== '' && !blockedNow && !cappedNow)), true);

  // Opening Ask moves focus to its heading, once it has one (final review, finding 3).
  useEffect(() => {
    if (focused.current || status.isPending) return;
    const heading = panel.current?.querySelector<HTMLElement>('h1, h2');
    if (heading) {
      heading.focus({ preventScroll: true });
      focused.current = true;
    }
  });

  const dropAbout = () => { setSearch((p) => { const n = new URLSearchParams(p); n.delete('about'); return n; }, { replace: true, preventScrollReset: true }); };
  const addBack = () => {
    if (last === null) return;
    nav({ pathname: loc.pathname, search: `?about=${last}` }, { replace: true, preventScrollReset: true });   // as aboutParam writes it: colons kept
    setNonce((n) => n + 1);
  };
  // History and back return to the question as it was, an unsent About too (the History view's own address has no
  // conversation in it). New, or another conversation opened from History, starts with no About and nothing to add
  // back (Argon follow-up 6).
  const backTo = useRef<string | null>(null);
  const toHistory = () => { backTo.current = `${cid !== null ? `/ask/c/${cid}` : '/ask'}${keep}`; go('/ask/history'); };
  const fresh = (path: string) => { asking.reset(); setLast(null); go(path); };
  const startNew = () => { setDraft(''); fresh('/ask'); };
  const open = (id: number) => {
    const from = backTo.current;
    if (from !== null && from.split('?')[0] === `/ask/c/${id}`) { asking.reset(); go(from); } else fresh(`/ask/c/${id}`);
  };
  // Send and Ask again both carry the About the chip shows (Argon follow-up 7).
  const send = (q: string) => void asking.ask(q, chip && aboutIn ? aboutIn : undefined, chip?.about);
  const viewer = book.role !== 'manager';
  const parent = book.kind === 'parent';
  const name = parentName(book);
  const head = (warn: string | null) => (
    <Head book={book} view={view} viewer={viewer} warn={warn} onHistory={toHistory}
      onBack={() => go(backTo.current ?? '/ask')} onNew={startNew} />
  );
  const title = fill(C.ASK_TITLE, { book: book.name });

  if (sample) {
    return (
      <section ref={panel} className="askp" aria-label={title}>
        <header className="askp__head"><div className="askp__bar"><h1 className="askp__title" tabIndex={-1}>{title}</h1></div></header>
        <div className="askp__body"><OffState viewer={viewer} slug={book.slug} sample /></div>
      </section>
    );
  }
  if (status.isPending) return <section ref={panel} className="askp" aria-label={title}>{head(null)}<div className="askp__body"><Skeleton lines={4} /></div></section>;
  if (status.isError) {
    return (
      <section ref={panel} className="askp" aria-label={title}>{head(null)}
        <div className="askp__body"><Notice tone="error"><p>{status.error.message}</p><Button variant="quiet" onClick={() => status.refetch()}>{TRY_AGAIN}</Button></Notice></div>
      </section>
    );
  }
  const s = status.data;
  if (!s.on) {
    return (
      <section ref={panel} className="askp" aria-label={title}>{head(null)}
        <div className="askp__body"><OffState viewer={viewer} slug={book.slug} /></div>
      </section>
    );
  }
  if (!s.seen) {
    return (
      <section ref={panel} className="askp" aria-label={C.BEFORE_TITLE}>
        <div className="askp__body"><Disclosure s={s} book={book} onNotNow={() => nav(bookHref(book.slug, '/'))} /></div>
      </section>
    );
  }

  const blocked = s.gateway.state !== 'ok';
  const capped = !!s.budget?.cap_line;
  const busy = asking.live !== null && !asking.live.done && !asking.live.error;
  const placeholder = asking.live?.card ? C.WAITING_CARD : blocked ? gw(C.PAUSED_BOX) : capped ? fill(C.CAP_BOX, { date: nextMonth() })
    : cid !== null || asking.live ? C.FOLLOW_UP : parent ? fill(C.BOX_PLACEHOLDER_PARENT, { name }) : C.BOX_PLACEHOLDER;
  const examples = parent ? C.EXAMPLES_PARENT.map((q) => fill(q, { name })) : C.EXAMPLES_HOUSEHOLD;
  const showConversation = cid !== null || asking.live !== null;
  return (
    <section ref={panel} className="askp" aria-label={title}>
      {head(s.budget?.warn ?? null)}
      <div className="askp__body">
        {view === 'history' ? <History onOpen={open} /> : <>
          {blocked && <GatewayState s={s} />}
          {!blocked && capped && <CapState s={s} slug={book.slug} />}
          {!showConversation && !blocked && !capped && (
            <div className="empty-ask">
              <h2>{fill(C.EMPTY_TITLE, { book: book.name })}</h2>
              <p className="muted">{parent ? fill(C.EMPTY_BODY_PARENT, { name }) : C.EMPTY_BODY}</p>
              <div className="examples">
                {examples.map((q) => (
                  <button key={q} type="button" className="example" onClick={() => setDraft(q)}>
                    <MessageCircleQuestionMark size={20} aria-hidden="true" />{q}
                  </button>
                ))}
              </div>
              <p className="small muted">{C.EXAMPLES_NOTE}</p>
            </div>
          )}
          {showConversation && (
            <Conversation conversationId={cid} live={asking.live} labels={asking.labels} me={me.data?.user.display_name ?? ''}
              onStop={asking.stop} onAskAgain={send} onNew={startNew} />
          )}
        </>}
      </div>
      {view === 'ask' && (
        <>
          {aboutIn && <div className="askp__chip"><AboutChip state={about} removed={removed} onRemove={dropAbout} onAddBack={addBack} /></div>}
          <Composer value={draft} onChange={setDraft} disabled={blocked || capped || busy} placeholder={placeholder}
            onSend={(text) => { setDraft(''); tour.done(); send(text.trim()); }}
            onFirstKey={() => { prewarm().catch(() => {}); }}
            about={chip ? { sent: chip.sent, chips: chip.chips, labels: chip.labels } : null}
            tour={{ show: tour.show, example: blocked, onToggle: tour.toggle, onDone: tour.done }} />
        </>
      )}
    </section>
  );
}
