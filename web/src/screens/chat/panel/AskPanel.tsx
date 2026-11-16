// "Ask about this" (phase 13 spec, The panel): Ask in a sheet on the page you're on, a bottom sheet on phones and a
// 420 px panel from 900 px. The chip says what the question is about, the suggestions fit the page, and the box shows
// the about line as it will be sent. Its root stays mounted once loaded, so closing keeps the conversation and any
// answer still arriving; one that finishes while it's closed shows "Answer ready · Open" (P3).
import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import { useMe } from '../../../api/hooks';
import type { BookSummary } from '../../../api/types';
import { aboutParam, type AboutIn, type Surface } from '../../../ask/about';
import { focusBack } from '../../../ask/focus';
import { closeAsk, reopenAsk, useAskState } from '../../../ask/store';
import { bookHref, useBook } from '../../../book/BookContext';
import { ASK, TRY_AGAIN } from '../../../lib/copy';
import { Button } from '../../../ui/Button';
import { Notice } from '../../../ui/Notice';
import { Sheet } from '../../../ui/Sheet';
import { Skeleton } from '../../../ui/Skeleton';
import { UndoToast } from '../../../ui/UndoToast';
import { AboutChip } from '../AboutChip';
import { useChatStatus } from '../api';
import { fill, prewarm } from '../askApi';
import { Composer } from '../Composer';
import { Conversation } from '../Conversation';
import * as C from '../copy';
import { gw } from '../../../lib/gatewayName';
import { CapState, Disclosure, GatewayState, nextMonth, OffState } from '../states';
import { useAboutReply } from '../useAboutReply';
import { useAsk } from '../useAsk';
import { useAskTour } from '../useAskTour';
import { suggestionsFor } from './suggestions';
import { Sep } from '../../../ui/Sep';
import '../ask.css';
import './panel.css';

/** What this panel's conversation is about, and which page asked. */
type Thread = { key: string; about: AboutIn; surface: Surface };
const keyOf = (about: AboutIn, surface: Surface) => `${surface.kind}|${aboutParam(about)}`;

export default function AskPanel() {
  const s = useAskState();
  const book = useBook() as BookSummary;
  const me = useMe();
  const nav = useNavigate();
  const sample = book.sample === true;
  const status = useChatStatus(!sample);   // a Sample asks the chat API nothing
  const [thread, setThread] = useState<Thread | null>(null);
  const [cid, setCid] = useState<number | null>(null);
  const [draft, setDraft] = useState('');
  const [removed, setRemoved] = useState(false);
  const [nonce, setNonce] = useState(0);
  const [toast, setToast] = useState(false);
  const asking = useAsk(cid, setCid);
  const box = useRef<HTMLTextAreaElement>(null);
  const closedWhileBusy = useRef(false);
  const busy = asking.live !== null && !asking.live.done && !asking.live.error;
  const about = useAboutReply(sample ? null : (thread?.about ?? null), nonce);

  // Each open from a button: the same thing resumes; something else starts a new conversation, unless an answer is
  // still arriving (Engineering choice 9). /about runs again on every open.
  useEffect(() => {
    if (!s.open || !s.about || !s.surface) return;
    const key = keyOf(s.about, s.surface);
    if (thread === null || (thread.key !== key && !busy)) {
      asking.reset();
      setCid(null);
      setDraft('');
      setRemoved(false);
      setThread({ key, about: s.about, surface: s.surface });
    }
    setNonce((n) => n + 1);
  }, [s.seq]); // eslint-disable-line react-hooks/exhaustive-deps

  // Closed while an answer was arriving: when it's done, say so (nothing finishes unseen).
  useEffect(() => {
    if (s.open) {
      closedWhileBusy.current = false;
      setToast(false);
    } else if (busy) {
      closedWhileBusy.current = true;
    }
  }, [s.open]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!busy && closedWhileBusy.current && !s.open) {
      closedWhileBusy.current = false;
      setToast(true);
    }
  }, [busy]); // eslint-disable-line react-hooks/exhaustive-deps

  // Focus goes to the box once there is one (P27); before then the Sheet left it on the title.
  useLayoutEffect(() => {
    const el = box.current;
    const at = document.activeElement;
    if (s.open && el && !el.disabled && (at === document.body || (at instanceof HTMLElement && at.classList.contains('sheet__title')))) el.focus();
  });

  const st = status.data;
  const ready = !!st && st.on && st.seen;
  const blocked = ready && st.gateway.state !== 'ok';
  const capped = ready && !blocked && !!st.budget?.cap_line;
  const chip = !removed && about.status === 'ready' ? about.reply : null;
  const tour = useAskTour(me.data?.user.id ?? null, s.open && ready && (chip !== null || (draft.trim() !== '' && !blocked && !capped)));
  const started = cid !== null || asking.live !== null;
  const viewer = book.role !== 'manager';

  function send(text: string) {
    setDraft('');
    tour.done();
    void asking.ask(text.trim(), chip && thread ? thread.about : undefined, chip?.about);
  }
  function startOver() {
    asking.reset();
    setCid(null);
    setDraft('');
  }
  function openInAsk() {
    const q = chip && thread ? `?about=${aboutParam(thread.about)}` : '';
    nav(bookHref(book.slug, cid !== null ? `/ask/c/${cid}${q}` : `/ask${q}`), { state: { draft } });
  }

  const placeholder = asking.live?.card ? C.WAITING_CARD : blocked ? gw(C.PAUSED_BOX)
    : capped ? fill(C.CAP_BOX, { date: nextMonth() }) : started ? C.FOLLOW_UP : '';
  let body: ReactNode;
  if (sample) {
    body = <OffState viewer={viewer} slug={book.slug} sample />;
  } else if (status.isError) {
    body = <Notice tone="error"><p>{status.error.message}</p><Button variant="quiet" onClick={() => void status.refetch()}>{TRY_AGAIN}</Button></Notice>;
  } else if (!st) {
    body = <Skeleton lines={3} />;
  } else if (!st.on) {
    body = <OffState viewer={viewer} slug={book.slug} />;
  } else if (!st.seen) {
    body = <Disclosure s={st} book={book} onNotNow={closeAsk} />;
  } else {
    body = (
      <>
        {blocked && <GatewayState s={st} />}
        {capped && <CapState s={st} slug={book.slug} />}
        {!started && !blocked && !capped && thread && (
          <div className="examples ask-sugg">
            {suggestionsFor(thread.surface, viewer, new Date()).map((q) => (
              <button key={q} type="button" className="example" onClick={() => { setDraft(q); box.current?.focus(); }}>{q}</button>
            ))}
          </div>
        )}
        {started && (
          <Conversation conversationId={cid} live={asking.live} labels={asking.labels} me={me.data?.user.display_name ?? ''}
            onStop={asking.stop} onAskAgain={send} onNew={startOver} />
        )}
        <Composer value={draft} onChange={setDraft} onSend={send} disabled={blocked || capped || busy} placeholder={placeholder}
          quiet boxRef={box} onFirstKey={() => { prewarm().catch(() => {}); }}
          about={chip ? { sent: chip.sent, chips: chip.chips, labels: chip.labels } : null}
          tour={{ show: tour.show, example: blocked, onToggle: tour.toggle, onDone: tour.done }}
          extra={started && !busy ? <Button variant="quiet" onClick={openInAsk}>{C.OPEN_IN_ASK}</Button> : null} />
      </>
    );
  }
  return (
    <>
      <Sheet open={s.open} onClose={closeAsk} title={ASK} focusRef={box} className="askpanel" returnTo={() => focusBack(s.opener)} keepsDraft
        onEscape={() => { if (!tour.show) return false; tour.hide(); return true; }}>
        {!sample && (
          <div className="askpanel__chip">
            <AboutChip state={about} removed={removed} onRemove={() => { setRemoved(true); }}
              onAddBack={() => { setRemoved(false); setNonce((n) => n + 1); }} />
          </div>
        )}
        {body}
      </Sheet>
      {toast && (
        <UndoToast text={C.ANSWER_READY} onClose={() => { setToast(false); }}
          link={<><Sep /><button type="button" className="link" onClick={() => { setToast(false); reopenAsk(); }}>{C.OPEN}</button></>} />
      )}
    </>
  );
}
