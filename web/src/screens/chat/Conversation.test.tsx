import { fireEvent, screen } from '@testing-library/react';
import { useState } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { setCurrentBook } from '../../api/book';
import { callsTo, reply, stubFetch, wrapBook } from '../../test-utils';
import type { Conversation as Detail } from './askApi';
import { Conversation } from './Conversation';
import { useAsk } from './useAsk';

afterEach(() => { vi.unstubAllGlobals(); setCurrentBook('ours'); });

const EMPTY: Detail = { id: 12, title: 'Cover a year', ended: false, requests: 0, long_line: null, labels: {}, turns: [] };
const DETAIL: Detail = {
  id: 12, title: 'Dining this year and last', ended: false, requests: 2, long_line: null,
  labels: { 'Person 2': 'Alex', 'Account 2': 'Rewards Card ••4402' },
  turns: [{
    turn_id: 't_1', asked: 'Are we spending more on dining than last year?', sent: 'Are we spending more on dining than last year?',
    chips: [], as_written: true, who: 'JR', when: 'Today 9:41 AM',
    steps: [{ tool: 'spending_by_category', done: 'Looked at spending by category' }],
    answer: "Yes. Dining came to **$9,184**. About 60% is on Person 2's Account 2.", stop: 'end_turn', line: null,
    meta: '11 seconds · $0.09', looked_into: false, unfinished: false,
    saw: [{ key: 't_1.2', name: 'spending_by_category', title: 'Spending by category', summary: '16 categories. No store names.', is_error: false, payload: { period: { start: '2025-10-01' } } }],
    approval: { state: 'approved', line: 'JR approved 9 store rows for this conversation.', log_key: 't_1.3' },
  }],
};

function ndjson(events: object[]) {
  return () => new Response(events.map((e) => JSON.stringify(e)).join('\n') + '\n', { status: 200 });
}

function Host({ start = null, onAskAgain = vi.fn() }: { start?: number | null; onAskAgain?: (q: string) => void }) {
  const [id, setId] = useState<number | null>(start);
  const a = useAsk(id, setId);
  return (
    <>
      <button type="button" onClick={() => void a.ask('Can we cover a year on one income?')}>go</button>
      <Conversation conversationId={id} live={a.live} labels={a.labels} me="JR" onStop={a.stop} onAskAgain={onAskAgain} onNew={vi.fn()} />
    </>
  );
}

describe('a conversation', () => {
  it('replays a turn: what was sent, the steps, names with the alias, what Claude saw and the time and cost', async () => {
    stubFetch({ '/api/chat/conversations/12': DETAIL });
    wrapBook(<Conversation conversationId={12} live={null} labels={{}} me="JR" onStop={vi.fn()} onAskAgain={vi.fn()} onNew={vi.fn()} />);
    expect(await screen.findByText('Are we spending more on dining than last year?')).toBeInTheDocument();
    expect(screen.getByText('Sent as written')).toBeInTheDocument();
    expect(screen.getByText('JR · Today 9:41 AM')).toBeInTheDocument();
    expect(screen.getByText('Looked at spending by category')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Alex. Sent as Person 2' })).toBeInTheDocument();
    expect(screen.getByText('11 seconds · $0.09')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'See them in the log' })).toHaveAttribute('href', '/b/ours/settings/chat/sent?open=t_1.3');
    fireEvent.click(screen.getByRole('button', { name: /What Claude saw \(1\)/ }));
    expect(screen.getByText('16 categories. No store names.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Show what was sent/ }));
    expect(screen.getByText(/"start": "2025-10-01"/)).toBeInTheDocument();
    expect(screen.getByText('Names with a dotted line were sent as aliases. Tap one to see the alias.')).toBeInTheDocument();
  });

  it('streams a live turn with a working line, then ticked steps, the answer and the cost', async () => {
    stubFetch({
      'POST /api/chat/ask': ndjson([
        { type: 'conversation', id: 12, note: null, turn_id: 't_9' }, { type: 'labels', labels: { 'Person 2': 'Alex' } },
        { type: 'redacted', text: 'Can we cover a year on one income?', chips: [] },
        { type: 'status', tool: 'cash_flow', text: 'Looking at money in and out', done: 'Looked at money in and out' },
        { type: 'text', delta: "Mostly. Person 2's pay covers $7,350 a month." },
        { type: 'done', stop: 'end_turn', line: null, answer: '', long_line: null, conversation_id: 12, turn_id: 't_9', requests: 2, cost_cents: 9, parts: 3, bytes: 900, meta: '9 seconds · $0.09' }]),
      '/api/chat/conversations/12': EMPTY,
    });
    wrapBook(<Host />);
    fireEvent.click(screen.getByRole('button', { name: 'go' }));
    expect(await screen.findByText('9 seconds · $0.09')).toBeInTheDocument();
    expect(screen.getByText('Looked at money in and out')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Alex. Sent as Person 2' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Stop' })).toBeNull();
  });

  it('text after Stop is not appended', async () => {
    let push: (e: object) => void = () => {};
    let end: () => void = () => {};
    const body = new ReadableStream<Uint8Array>({ start(c) { const enc = new TextEncoder(); push = (e) => c.enqueue(enc.encode(JSON.stringify(e) + '\n')); end = () => c.close(); } });
    const fetchMock = stubFetch({ 'POST /api/chat/ask': () => new Response(body, { status: 200 }), 'POST /api/chat/turns/': { ok: true }, '/api/chat/conversations/12': EMPTY });
    wrapBook(<Host />);
    fireEvent.click(screen.getByRole('button', { name: 'go' }));
    push({ type: 'conversation', id: 12, note: null, turn_id: 't_9' });
    push({ type: 'text', delta: 'So far' });
    fireEvent.click(await screen.findByRole('button', { name: 'Stop' }));
    await vi.waitFor(() => expect(callsTo(fetchMock, 'POST', '/api/chat/turns/t_9/stop')).toHaveLength(1));
    push({ type: 'text', delta: ' and more' });
    push({ type: 'done', stop: 'stopped', line: 'You stopped this answer.', answer: '', long_line: null, conversation_id: 12, turn_id: 't_9', requests: 1, cost_cents: 3, parts: 2, bytes: 400, meta: '2 seconds · $0.03' });
    end();
    expect(await screen.findByText('You stopped this answer.')).toBeInTheDocument();
    expect(screen.getByText('So far')).toBeInTheDocument();
    expect(screen.queryByText(/and more/)).toBeNull();
  });

  it('a dropped answer keeps what arrived and offers Ask again', async () => {
    const onAskAgain = vi.fn();
    stubFetch({
      'POST /api/chat/ask': ndjson([{ type: 'conversation', id: 12, note: null, turn_id: 't_9' }, { type: 'text', delta: 'Mostly. On' },
        { type: 'done', stop: 'dropped', line: 'The gateway stopped answering, so this answer is incomplete.', answer: '', long_line: null, conversation_id: 12, turn_id: 't_9', requests: 1, cost_cents: 2, parts: 2, bytes: 400, meta: '4 seconds · $0.02' }]),
      '/api/chat/conversations/12': EMPTY,
    });
    wrapBook(<Host onAskAgain={onAskAgain} />);
    fireEvent.click(screen.getByRole('button', { name: 'go' }));
    expect(await screen.findByText('The gateway stopped answering, so this answer is incomplete.')).toBeInTheDocument();
    expect(screen.getByText('Mostly. On')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Ask again' }));
    expect(onAskAgain).toHaveBeenCalledWith('Can we cover a year on one income?');
  });

  it('a 409 off line switches to the off state and refreshes the book', async () => {
    stubFetch({ 'POST /api/chat/ask': () => reply({ error: 'Chat is off for this book. A manager can turn it on in Settings → Chat.' }, 409) });
    const { qc } = wrapBook(<Host />);
    const spy = vi.spyOn(qc, 'invalidateQueries');
    fireEvent.click(screen.getByRole('button', { name: 'go' }));
    expect(await screen.findByText('Chat is off for this book. A manager can turn it on in Settings → Chat.')).toBeInTheDocument();
    expect(spy).toHaveBeenCalledWith({ queryKey: ['chat', 'status'] });
    expect(spy).toHaveBeenCalledWith({ queryKey: ['me'] });
  });

  it('shows the store-names card while it waits and the viewer card for a viewer', async () => {
    stubFetch({
      'POST /api/chat/ask': ndjson([{ type: 'conversation', id: 12, note: null, turn_id: 't_9' },
        { type: 'approval', state: 'viewer', managers: ['JR', 'Alex'], where: 'Look into' }]),
      '/api/chat/conversations/12': EMPTY,
    });
    wrapBook(<Host />, { role: 'viewer', kind: 'parent' });
    fireEvent.click(screen.getByRole('button', { name: 'go' }));
    expect(await screen.findByText('JR or Alex can see the names in Look into, or ask the same question and approve them.')).toBeInTheDocument();
  });
  it('draws the steps first, then the card while it waits, earlier steps staying visible (chat-approve mockup)', async () => {
    const card = { call_id: 'toolu_m1', reason: 'Totals show 5 new monthly payments.', count: 1, first: 'Oct 18', last: 'Oct 18',
      names: [{ name: 'StreamBox', count: 1 }], rows: [{ date: 'Oct 18', store: 'StreamBox', amount_cents: -1599, category: 'subscriptions', account: 'Account 2' }],
      payees: [], accounts: [{ alias: 'Account 2', label: 'Rewards Card ••4402' }], until: '10:12 AM', more: false, hash: 'h_1' };
    stubFetch({
      'POST /api/chat/ask': ndjson([{ type: 'conversation', id: 12, note: null, turn_id: 't_9' },
        { type: 'status', tool: 'recurring', text: 'Looking at recurring payments', done: 'Looked at recurring payments' },
        { type: 'status', tool: 'merchant_detail', text: 'Asking for store names', done: 'Asked for store names' },
        { type: 'approval', state: 'ask', card }]),
      '/api/chat/conversations/12': EMPTY,
    });
    wrapBook(<Host />);
    fireEvent.click(screen.getByRole('button', { name: 'go' }));
    const group = await screen.findByRole('group', { name: 'Claude asks for store names' });
    const step = screen.getByText('Looked at recurring payments');
    expect(step.compareDocumentPosition(group) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('a replayed turn reads steps, then the approval line, then the answer', async () => {
    stubFetch({ '/api/chat/conversations/12': DETAIL });
    wrapBook(<Conversation conversationId={12} live={null} labels={{}} me="JR" onStop={vi.fn()} onAskAgain={vi.fn()} onNew={vi.fn()} />);
    const step = await screen.findByText('Looked at spending by category');
    const approval = screen.getByText('JR approved 9 store rows for this conversation.');
    const answer = screen.getByText(/Dining came to/);
    expect(step.compareDocumentPosition(approval) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(approval.compareDocumentPosition(answer) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('a replayed turn that never finished says so plainly and does not crash', async () => {
    const base = DETAIL.turns[0]!;
    const unfinished = { ...base, turn_id: 't_2', answer: '', stop: null, line: null, meta: null, unfinished: true, saw: [], steps: [], approval: null };
    stubFetch({ '/api/chat/conversations/12': { ...DETAIL, turns: [base, unfinished] } });
    wrapBook(<Conversation conversationId={12} live={null} labels={{}} me="JR" onStop={vi.fn()} onAskAgain={vi.fn()} onNew={vi.fn()} />);
    expect(await screen.findByText("This question didn't finish.")).toBeInTheDocument();
    expect(screen.getAllByText('11 seconds · $0.09')).toHaveLength(1);
    expect(screen.queryByRole('button', { name: 'Stop' })).toBeNull();
  });
  it('an older conversation answered before turns were recorded shows no end line', async () => {
    const base = DETAIL.turns[0]!;
    const legacy = { ...base, turn_id: 't_old', stop: null, line: null, meta: null, when: '', unfinished: false, saw: [], steps: [], approval: null };
    stubFetch({ '/api/chat/conversations/12': { ...DETAIL, turns: [legacy] } });
    wrapBook(<Conversation conversationId={12} live={null} labels={{}} me="JR" onStop={vi.fn()} onAskAgain={vi.fn()} onNew={vi.fn()} />);
    expect(await screen.findByText(/Dining came to/)).toBeInTheDocument();
    expect(screen.queryByText("This question didn't finish.")).toBeNull();
  });
  it('while a turn is streaming, its replayed row is not shown a second time', async () => {
    let push: (e: object) => void = () => {};
    const body = new ReadableStream<Uint8Array>({ start(c) { const enc = new TextEncoder(); push = (e) => c.enqueue(enc.encode(JSON.stringify(e) + '\n')); } });
    const running = { ...DETAIL.turns[0]!, turn_id: 't_9', asked: 'Can we cover a year on one income?', sent: 'Can we cover a year on one income?',
      answer: '', stop: null, line: null, meta: null, unfinished: true, saw: [], steps: [], approval: null };
    const fetchMock = stubFetch({ 'POST /api/chat/ask': () => new Response(body, { status: 200 }), '/api/chat/conversations/12': { ...DETAIL, turns: [running] } });
    wrapBook(<Host />);
    fireEvent.click(screen.getByRole('button', { name: 'go' }));
    push({ type: 'conversation', id: 12, note: null, turn_id: 't_9' });
    push({ type: 'text', delta: 'So far' });
    expect(await screen.findByText('So far')).toBeInTheDocument();
    await vi.waitFor(() => expect(callsTo(fetchMock, 'GET', '/api/chat/conversations/12').length).toBeGreaterThan(0));
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.getAllByText('Can we cover a year on one income?')).toHaveLength(1);
    expect(screen.queryByText("This question didn't finish.")).toBeNull();
  });
});
