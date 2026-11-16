// Your conversations in this book (spec 5.1, 5.2; design pass screen 8): listed only for you, newest first, by Today,
// This week and Earlier. No search in plan B (JR decision 10). Deleting takes a conversation off your list; what it
// sent stays in the book's log.
import { useQueryClient } from '@tanstack/react-query';
import { Store, Trash2 } from 'lucide-react';
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { currentBook } from '../../api/book';
import { useBook, useBookTo } from '../../book/BookContext';
import { setQueryDataIfStillIn } from '../../queryClient';
import { useRemoval } from '../../lib/useRemoval';
import { ConfirmSheet } from '../../ui/ConfirmSheet';
import { Notice } from '../../ui/Notice';
import { RemovalLine } from '../../ui/RemovalLine';
import { Skeleton } from '../../ui/Skeleton';
import { deleteConversation, fill, useConversations, type ConversationRow } from './askApi';
import * as C from './copy';
import { Sep } from '../../ui/Sep';

const questions = (n: number) => (n === 1 ? C.ONE_QUESTION : fill(C.N_QUESTIONS, { n }));
const requests = (n: number) => (n === 1 ? '1 request' : `${n} requests`);

export function History({ onOpen }: { onOpen: (id: number) => void }) {
  const book = useBook();
  const to = useBookTo();
  const qc = useQueryClient();
  const q = useConversations();
  const [doomed, setDoomed] = useState<ConversationRow | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // The list can go with its last row, so the line itself holds focus after a delete (THO-1).
  const removal = useRemoval();

  async function remove(row: ConversationRow) {
    setBusy(true);
    setError(null);
    removal.clear();
    const bookAtStart = currentBook();
    try {
      await deleteConversation(row.id);
      setQueryDataIfStillIn<{ conversations: ConversationRow[] }>(qc, bookAtStart, ['chat', 'conversations'],
        (old) => old && { conversations: old.conversations.filter((c) => c.id !== row.id) });
      qc.removeQueries({ queryKey: ['chat', 'conversation', row.id] });
      removal.removed(fill(C.DELETED, { title: row.title }));
      setDoomed(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (q.isPending) return <Skeleton lines={4} />;
  if (q.isError) return <Notice tone="error">{q.error.message}</Notice>;
  const rows = q.data.conversations;
  const line = <RemovalLine removal={removal} holdsFocus />;
  if (rows.length === 0) return <>{line}<p className="muted">{fill(C.HISTORY_EMPTY, { book: book?.name ?? '' })}</p></>;
  return (
    <>
      {line}
      <section className="card convs" aria-label={C.HISTORY_TITLE}>
        {(['today', 'week', 'earlier'] as const).map((g) => {
          const group = rows.filter((r) => r.group === g);
          if (group.length === 0) return null;
          return (
            <div key={g}>
              <div className="conv__day">{C.GROUPS[g]}</div>
              {group.map((r) => (
                <div key={r.id} className="conv">
                  <button type="button" className="conv__title" onClick={() => onOpen(r.id)}>{r.title}</button>
                  <span className="conv__meta">
                    <span>{r.when}</span><Sep /><span>{questions(r.questions)}</span>
                    {r.store_names && <><Sep /><span className="conv__store"><Store size={20} aria-hidden="true" />{C.STORE_NAMES_SENT}</span></>}
                  </span>
                  <button type="button" className="del-btn" aria-label={`${C.DELETE} ${r.title}`} onClick={() => setDoomed(r)}>
                    <Trash2 size={20} aria-hidden="true" />{C.DELETE}
                  </button>
                </div>
              ))}
            </div>
          );
        })}
      </section>
      <p className="small muted">{C.HISTORY_FOOT} <Link to={to('/settings/chat/sent')}>{C.OPEN_LOG}</Link></p>
      <ConfirmSheet open={doomed !== null} onClose={() => setDoomed(null)} title={fill(C.DELETE_TITLE, { title: doomed?.title ?? '' })}
        body={doomed && doomed.requests > 0 ? fill(C.DELETE_BODY, { requests: requests(doomed.requests) }) : C.DELETE_BODY_NONE}
        action={C.DELETE} icon={Trash2} cancel={C.KEEP} busy={busy} error={error} onConfirm={() => doomed && void remove(doomed)}
        returnTo={removal.returnTo} />
    </>
  );
}
