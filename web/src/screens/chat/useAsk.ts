// Ask about this: a question may carry what it was asked about (ids only, cleaned to the request's own keys).
// One live question (spec 5.3): reads the turn stream and keeps the steps, the text, the card and the ending, then
// refreshes the conversation, the list and the status. Stop asks the NAS to stop (plan B ruling 8) and text that
// arrives after it isn't shown. A 409 means chat was turned off meanwhile: the status and the book are refreshed so
// the page shows the off state and the Ask button goes (review focus 5).
import { useQueryClient } from '@tanstack/react-query';
import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError, isAbort } from '../../api/client';
import { cleanAbout, type AboutIn } from '../../ask/about';
import { stopTurn, type AboutWire, type ApprovalEvent, type AskEvent, type Card, type Chip, type DoneEvent } from './askApi';
import { STOPPED, STREAM_BROKE } from './copy';
import { readTurn } from './stream';

export type LiveStep = { tool: string; text: string; done: string };
export type LiveTurn = {
  asked: string; about?: AboutWire | null; turnId: string | null; sent: string | null; chips: Chip[]; steps: LiveStep[]; text: string; card: Card | null;
  viewer: { managers: string[]; where: string } | null; approval: { state: 'approved' | 'declined'; line: string } | null;
  note: string | null; done: DoneEvent | null; error: string | null; stopping: boolean;
};

const fresh = (asked: string, about: AboutWire | null): LiveTurn => ({
  asked, about, turnId: null, sent: null, chips: [], steps: [], text: '', card: null, viewer: null, approval: null, note: null,
  done: null, error: null, stopping: false,
});

function applyApproval(t: LiveTurn, e: ApprovalEvent): LiveTurn {
  if (e.state === 'ask') return { ...t, card: e.card };
  if (e.state === 'viewer') return { ...t, viewer: { managers: e.managers, where: e.where } };
  return { ...t, card: null, approval: { state: e.state, line: e.line } };
}

export function useAsk(conversationId: number | null, onConversation: (id: number) => void) {
  const qc = useQueryClient();
  const [live, setLive] = useState<LiveTurn | null>(null);
  const [labels, setLabels] = useState<Record<string, string>>({});
  const ctrl = useRef<AbortController | null>(null);
  const turnId = useRef<string | null>(null);
  const stopped = useRef(false);
  const onConv = useRef(onConversation);
  onConv.current = onConversation;

  useEffect(() => () => ctrl.current?.abort(), []);

  const ask = useCallback(async (question: string, about?: AboutIn, wire?: AboutWire) => {
    ctrl.current?.abort();
    const c = new AbortController();
    ctrl.current = c;
    stopped.current = false;
    turnId.current = null;
    performance.mark('ask-send');
    setLive(fresh(question, about && wire ? wire : null));
    const update = (f: (t: LiveTurn) => LiveTurn) => { if (!c.signal.aborted) setLive((t) => (t ? f(t) : t)); };
    let cid = conversationId;
    try {
      await readTurn({ question, conversation_id: conversationId, ...(about ? { about: cleanAbout(about) } : {}) }, (e: AskEvent) => {
        switch (e.type) {
          case 'conversation':
            cid = e.id;
            turnId.current = e.turn_id;
            requestAnimationFrame(() => performance.mark('ask-first-status'));   // the working line is on screen (spec 12)
            update((t) => ({ ...t, turnId: e.turn_id, note: e.note }));
            if (e.id !== conversationId) onConv.current(e.id);
            break;
          case 'labels': setLabels(e.labels); break;
          case 'redacted': update((t) => ({ ...t, sent: e.text, chips: e.chips })); break;
          case 'status': update((t) => ({ ...t, steps: [...t.steps, { tool: e.tool, text: e.text, done: e.done }] })); break;
          case 'text': if (!stopped.current) update((t) => ({ ...t, text: t.text + e.delta })); break;
          case 'approval': update((t) => applyApproval(t, e)); break;
          case 'done': update((t) => ({ ...t, done: e, card: null, stopping: false })); break;
        }
      }, c.signal);
    } catch (e) {
      if (stopped.current && (isAbort(e) || c.signal.aborted)) {
        setLive((t) => (t ? { ...t, stopping: false, error: STOPPED, card: null } : t));
        return;
      }
      if (isAbort(e) || c.signal.aborted) return;
      update((t) => ({ ...t, error: e instanceof ApiError ? e.message : STREAM_BROKE }));     // plain words only
      if (e instanceof ApiError && e.status === 409) {
        void qc.invalidateQueries({ queryKey: ['chat', 'status'] });
        void qc.invalidateQueries({ queryKey: ['me'] });
      }
      return;
    }
    if (cid !== null) void qc.invalidateQueries({ queryKey: ['chat', 'conversation', cid] });
    void qc.invalidateQueries({ queryKey: ['chat', 'conversations'] });
    void qc.invalidateQueries({ queryKey: ['chat', 'status'] });
  }, [conversationId, qc]);

  const stop = useCallback(() => {
    stopped.current = true;
    setLive((t) => (t ? { ...t, stopping: true } : t));
    if (turnId.current) stopTurn(turnId.current).catch(() => ctrl.current?.abort());
    else ctrl.current?.abort();
  }, []);

  const reset = useCallback(() => {
    ctrl.current?.abort();
    setLive(null);
    setLabels({});
  }, []);

  return { live, labels, ask, stop, reset };
}
