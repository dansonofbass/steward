// Unit-test fixtures for the Ask about this panel and its surfaces.
import type { AboutIn, Surface } from '../../../ask/about';
import type { AboutReply } from '../askApi';

export const STATUS = {
  on: true, can_change: true, changed: null, seen: true, disclosure: 'Steward sends Claude, an AI made by Anthropic, the numbers it needs to answer you.',
  off_line: 'Chat is off for this book. A manager can turn it on in Settings → Chat.',
  gateway: { state: 'ok', line: 'The gateway is answering.', last_answered: 'today at 10:04 AM', checked: 'today at 10:04 AM', checks: { redaction: true, key: true, categorizer: true }, away_long: false },
  budget: { line: 'This month: $3.12 of $10 · 26 questions', warn: null, cap_line: null, spent_cents: 312, cap_cents: 1000, questions: 26, model: 'claude-opus-5-5' },
  can_budget: true, models: [], members: ['JR', 'Alex'], managers: ['JR', 'Alex'], sent_month: { requests: 41, last: 'today at 10:03 AM' },
};
export const AWAY = { ...STATUS, gateway: { ...STATUS.gateway, state: 'away', line: "Chat needs the gateway, which isn't answering. It may be asleep or turned off." } };
export const ME = { user: { id: 1, username: 'jr', display_name: 'JR' }, session: { id: 1, device_label: 'Phone', created_at: '2026-10-01T00:00:00Z' }, books: [] };
export const DINING_IN: AboutIn = { kind: 'category', category: 'dining', month: '2026-10' };
export const DINING_SURFACE: Surface = { kind: 'category', category: 'dining', month: '2026-10', over: false };
export const DINING_REPLY: AboutReply = { about: { kind: 'category', category: 'dining', month: '2026-10' }, sent: "It's about Eating out (category dining) in October 2026.", chips: [], labels: {} };
export const CHECKING_IN: AboutIn = { kind: 'account', id: 12 };
export const CHECKING_REPLY: AboutReply = { about: { kind: 'account', account: 'Account 3' }, sent: "It's about Account 3.",
  chips: [{ start: 11, end: 20, label: 'Account 3', layer: 'alias' }], labels: { 'Account 3': 'Checking ••6789' } };
export const CONV7 = { id: 7, title: 'Is this higher than usual?', ended: false, requests: 1, long_line: null, labels: {}, turns: [] };
export const STARTED = { type: 'conversation', id: 7, note: null, turn_id: 't_1' };
export const DONE = (answer: string) => ({ type: 'done', stop: 'end_turn', line: null, answer, long_line: null, conversation_id: 7,
  turn_id: 't_1', requests: 1, cost_cents: 4, parts: 2, bytes: 900, meta: '3 seconds · $0.04' });
const HEADERS = { 'content-type': 'application/x-ndjson' };
/** The server streams an answer as text deltas and then `done`; a fixture `done` carries its answer, and this puts the
 *  same text ahead of it as that delta (the live turn shows deltas, not the done event's copy). */
const streamed = (e: object): object[] => {
  const d = e as { type?: string; answer?: string };
  return d.type === 'done' && d.answer ? [{ type: 'text', delta: d.answer }, e] : [e];
};
export const ndjson = (...events: object[]) => new Response(`${events.flatMap(streamed).map((e) => JSON.stringify(e)).join('\n')}\n`, { status: 200, headers: HEADERS });
/** A turn stream the test feeds one event at a time. */
export function held() {
  let ctrl!: ReadableStreamDefaultController<Uint8Array>;
  const body = new ReadableStream<Uint8Array>({ start(c) { ctrl = c; } });
  const enc = new TextEncoder();
  return {
    response: () => new Response(body, { status: 200, headers: HEADERS }),
    push: (e: object) => { for (const x of streamed(e)) ctrl.enqueue(enc.encode(`${JSON.stringify(x)}\n`)); },
    end: () => { ctrl.close(); },
  };
}
