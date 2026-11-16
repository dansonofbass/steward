import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Copy } from 'lucide-react';
import { useRef, useState, type ReactNode } from 'react';
import { useCanEdit } from '../../book/BookContext';
import { withCelebrate } from '../../lib/celebrations';
import { UNDONE } from '../../lib/copy';
import type { Part } from '../../lib/receipt';
import { Button } from '../../ui/Button';
import { Rich } from '../../ui/Rich';
import { getQuestions, keepApart, mergeQuestion, refresh, undoIt, type Question } from './api';
import * as C from './copy';
import { mergedLine, questionLine } from './lines';
import { SaidLine, type Said } from './Said';
import './sameaccount.css';

const plain = (text: string): Part[] => [{ text, bold: false }];
const message = (e: unknown) => (e instanceof Error ? e.message : 'Something went wrong.');
type Answer = Said & { done: boolean };   // done: answered, until an Undo brings the question back

/** "Same account?" (same-account spec, Asking): one card per open question, newest first, on Home above Needs
 *  attention and at the top of Accounts. After an answer the card stays and says what happened, with Undo; a merge
 *  gets the quiet cheer. A viewer reads the question without the buttons. Nothing shows while there is nothing to ask,
 *  or if the list can't load. */
export default function SameAccount() {
  const q = useQuery({ queryKey: ['same-accounts'], queryFn: getQuestions, staleTime: 60_000 });
  const qc = useQueryClient();
  const canEdit = useCanEdit();
  const [answers, setAnswers] = useState<Record<string, Answer>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const cards = useRef<Record<string, HTMLElement | null>>({});
  const open = q.data?.questions ?? [];
  // Every question that has an answer on the card and has left the list stays, so an Undo's refetch never blanks it.
  const answered = Object.keys(answers).filter((id) => !open.some((x) => x.id === id));
  if (open.length === 0 && answered.length === 0) return null;

  const say = (id: string, a: Answer) => { setAnswers((s) => ({ ...s, [id]: a })); };

  async function answer(item: Question, how: 'merge' | 'different') {
    if (busy) return;
    setBusy(item.id);
    try {
      if (how === 'merge') {
        const r = await mergeQuestion(item.id);
        say(item.id, { done: true, parts: mergedLine(r.merged), cheer: C.CHEER, undo: r.undo });
        const host = cards.current[item.id];
        if (host) void withCelebrate((c) => { c.closer({ over: host }); });
      } else {
        const r = await keepApart(item.id);
        say(item.id, { done: true, parts: plain(C.KEPT_APART), cheer: null, undo: r.undo });
      }
      await refresh(qc);
    } catch (e) {
      say(item.id, { done: false, parts: plain(message(e)), cheer: null, undo: null, error: true });
    } finally {
      setBusy(null);
    }
  }

  async function undo(id: string) {
    const a = answers[id];
    if (!a?.undo || busy) return;
    setBusy(id);
    try {
      await undoIt(a.undo);
      say(id, { done: false, parts: plain(UNDONE), cheer: null, undo: null });
      await refresh(qc);
    } catch (e) {
      say(id, { ...a, parts: plain(message(e)), error: true });
    } finally {
      setBusy(null);
    }
  }

  const card = (id: string, body: ReactNode) => (
    <section key={id} className="card same" aria-labelledby={`same-${id}`} ref={(el) => { cards.current[id] = el; }}>
      <h2 className="same__head eyebrow" id={`same-${id}`}><Copy size={18} aria-hidden="true" />{C.SAME_ACCOUNT}</h2>
      {body}
    </section>
  );
  const said = (id: string) => <SaidLine said={answers[id]} busy={busy === id} onUndo={() => { void undo(id); }} />;
  return (
    <div className="same-list">
      {answered.map((id) => card(id, said(id)))}
      {open.map((item) => {
        const a = answers[item.id];
        if (a?.done) return card(item.id, said(item.id));     // answered; the list hasn't read again yet
        return card(item.id, (
          <>
            <p className="same__line"><Rich parts={questionLine(item)} /></p>
            {a && said(item.id)}
            {canEdit ? (
              <div className="same__acts">
                <Button busy={busy === item.id} onClick={() => { void answer(item, 'merge'); }}>{C.MERGE_THEM}</Button>
                <Button variant="quiet" disabled={busy === item.id} onClick={() => { void answer(item, 'different'); }}>{C.THEYRE_DIFFERENT}</Button>
              </div>
            ) : <p className="small muted">{C.VIEWER}</p>}
          </>
        ));
      })}
    </div>
  );
}
