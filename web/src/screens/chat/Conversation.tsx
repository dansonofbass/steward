// A conversation: the turns the NAS has (GET /chat/conversations/{id}), then the live turn until the NAS lists it.
import { MessagesSquare } from 'lucide-react';
import { useConversation } from './askApi';
import * as C from './copy';
import { Notice } from '../../ui/Notice';
import { fromLive, fromTurn, TurnView } from './TurnView';
import type { LiveTurn } from './useAsk';

const ALIAS = /(?<![\w])(?:(?:Person|Child|Account|Payee) [1-9][0-9]{0,3}|Joint|Business|Parent)(?![\w])/;

type Props = {
  conversationId: number | null; live: LiveTurn | null; labels: Record<string, string>; me: string; onStop: () => void;
  onAskAgain: (q: string) => void; onNew: () => void;
};

export function Conversation({ conversationId, live, labels, me, onStop, onAskAgain, onNew }: Props) {
  const conv = useConversation(conversationId);
  const turns = conv.data?.turns ?? [];
  const listed = live?.turnId ? turns.some((t) => t.turn_id === live.turnId) : false;
  const showLive = live !== null && !(listed && live.done);
  // While the live turn is on screen, its replayed row (the NAS commits it before the stream says so) stays hidden.
  const shown = showLive && live?.turnId ? turns.filter((t) => t.turn_id !== live.turnId) : turns;
  const all = { ...(conv.data?.labels ?? {}), ...labels };
  const longLine = live?.done?.long_line ?? conv.data?.long_line ?? null;
  const texts = [...turns.map((t) => t.answer), live?.text ?? ''];
  const named = texts.some((t) => { const m = t.match(ALIAS); return m !== null && all[m[0]] !== undefined && all[m[0]] !== m[0]; });
  return (
    <div className="convo">
      {conv.isError && <Notice tone="error">{conv.error.message}</Notice>}
      {shown.map((t) => <TurnView key={t.turn_id} view={fromTurn(t)} labels={all} onAskAgain={onAskAgain} />)}
      {showLive && live && <TurnView view={fromLive(live, me)} labels={all} onStop={onStop} onAskAgain={onAskAgain} />}
      {longLine && (
        <p className="endline endline--muted">
          <MessagesSquare size={20} aria-hidden="true" />
          <span>{longLine} <button type="button" className="link" onClick={onNew}>{C.NEW_CONVERSATION}</button></span>
        </p>
      )}
      {named && <p className="small muted">{C.ALIAS_NOTE}</p>}
    </div>
  );
}
