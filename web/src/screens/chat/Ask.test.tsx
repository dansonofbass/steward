import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import { Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { setCurrentBook } from '../../api/book';
import type { BookSummary } from '../../api/types';
import { letTestingLibraryDriveFakeTimers, useFakeTimers } from '../../test-clock';
import { resetTourLoad } from '../../lib/askTour';
import { callsTo, renderAt, reply, stubFetch, wrapBook } from '../../test-utils';
import Ask from './Ask';
import { PREVIEW_DELAY_MS } from './Composer';
import { resetTourHidden } from './useAskTour';

afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); setCurrentBook('ours'); });

const DISCLOSURE = 'Steward sends Claude, an AI made by Anthropic, the numbers it needs to answer you: balances, income, spending totals, holdings, debts, ages, your state and tax facts. It replaces the names, account numbers, addresses, emails and birth dates it holds, apart from the gaps Privacy lists, and your gateway looks for others but can miss one. Store and payee names are sent only in rows a manager approves, and those rows stay in that conversation. In a row Steward reads as Zelle, a wire, a transfer or a payment app (Privacy lists the words), the name is sent as [name] unless the manager ticks that row. Every part of your data that is sent is kept in this book\'s log, which every member can read. Your conversations are listed only for you.';
const STATUS = {
  on: true, can_change: true, changed: null, seen: true, disclosure: DISCLOSURE,
  off_line: 'Chat is off for this book. A manager can turn it on in Settings → Chat.',
  gateway: { state: 'ok', line: 'The gateway is answering.', last_answered: 'today at 10:04 AM', checked: 'today at 10:04 AM', checks: { redaction: true, key: true, categorizer: true }, away_long: false },
  budget: { line: 'This month: $3.12 of $10 · 26 questions', warn: null, cap_line: null, spent_cents: 312, cap_cents: 1000, questions: 26, model: 'claude-opus-5-5' },
  can_budget: true, models: [], members: ['JR', 'Alex'], managers: ['JR', 'Alex'], sent_month: { requests: 41, last: 'today at 10:03 AM' },
};
const ME = { user: { id: 1, username: 'jr', display_name: 'JR' }, session: { id: 1, device_label: 'Phone', created_at: '2026-10-01T00:00:00Z' }, books: [] };

function mount(status: Record<string, unknown> = STATUS, book: Partial<BookSummary> = {}, extra: Record<string, unknown> = {}) {
  const fetchMock = stubFetch({ '/api/chat': status, '/api/auth/me': ME, ...extra });
  const r = wrapBook(<Routes><Route path="/b/:slug/ask/*" element={<Ask />} /></Routes>, book, '/b/ours/ask');
  return { fetchMock, ...r };
}

describe('the Ask page', () => {
  it('opens on the empty page; an example fills the box and does not send', async () => {
    const { fetchMock } = mount();
    expect(await screen.findByRole('heading', { name: 'Ask about Ours' })).toBeInTheDocument();
    expect(screen.getByText('Answers come from Claude. Steward replaces the account numbers and names it holds, except store and payee names a manager approves. Your gateway looks for other names and can miss one.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: "What's sent" })).toHaveAttribute('href', '/b/ours/settings/chat/sent');
    fireEvent.click(await screen.findByRole('button', { name: 'Can we cover a year on one income?' }));
    expect(screen.getByLabelText('Your question')).toHaveValue('Can we cover a year on one income?');
    expect(callsTo(fetchMock, 'POST', '/api/chat/ask')).toHaveLength(0);
  });

  it('is a page with History and New, and no Close (decision 3)', async () => {
    mount();
    expect(await screen.findByRole('button', { name: 'History' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'New' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Close' })).toBeNull();
  });

  it("the disclosure's Not now opens the book's Home", async () => {
    stubFetch({ '/api/chat': { ...STATUS, seen: false }, '/api/auth/me': ME });
    wrapBook(<Routes><Route path="/b/:slug" element={<p>Home</p>} /><Route path="/b/:slug/ask/*" element={<Ask />} /></Routes>, {}, '/b/ours/ask');
    fireEvent.click(await screen.findByRole('button', { name: 'Not now' }));
    expect(await screen.findByText('Home')).toBeInTheDocument();
  });

  it('moves focus to its heading when it opens', async () => {
    mount();
    await vi.waitFor(() => expect(screen.getByRole('heading', { name: 'Ask about Ours' })).toHaveFocus());
  });

  it('on the disclosure, focus starts at its heading', async () => {
    mount({ ...STATUS, seen: false });
    await vi.waitFor(() => expect(screen.getByRole('heading', { name: 'Before you ask' })).toHaveFocus());
  });

  it('shows the disclosure once, naming the members, and Start marks it read', async () => {
    const { fetchMock } = mount({ ...STATUS, seen: false }, {}, { 'POST /api/chat/seen': { seen: true } });
    expect(await screen.findByText(DISCLOSURE)).toBeInTheDocument();
    expect(screen.getByText('In Ours, the members are JR and Alex. You can read the log at any time in Settings → Chat.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Start' }));
    await vi.waitFor(() => expect(callsTo(fetchMock, 'POST', '/api/chat/seen')).toHaveLength(1));
    expect(await screen.findByText('Ask about the money in Ours')).toBeInTheDocument();
  });

  it('a Start that fails says so in plain words and stays on the disclosure', async () => {
    mount({ ...STATUS, seen: false }, {}, { 'POST /api/chat/seen': () => reply({ error: 'Something went wrong (500).' }, 500) });
    fireEvent.click(await screen.findByRole('button', { name: 'Start' }));
    expect(await screen.findByText('Something went wrong (500).')).toBeInTheDocument();
    expect(screen.getByText(DISCLOSURE)).toBeInTheDocument();
  });

  it('chat off: a manager gets the link to Settings, a viewer does not', async () => {
    mount({ ...STATUS, on: false });
    expect(await screen.findByText('Chat is off for this book')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Go to Settings → Chat' })).toBeInTheDocument();
  });

  it('chat off for a viewer', async () => {
    mount({ ...STATUS, on: false, can_change: false }, { role: 'viewer' });
    expect(await screen.findByText('Chat is off for this book')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Go to Settings → Chat' })).toBeNull();
    expect(screen.getByText("You're a viewer in this book. You can ask; a manager approves store and payee names.")).toBeInTheDocument();
  });

  it('The gateway away: says so with when it last answered, and the box is paused', async () => {
    mount({ ...STATUS, gateway: { ...STATUS.gateway, state: 'away', line: "Chat needs the gateway, which isn't answering. It may be asleep or turned off.", last_answered: 'today at 7:12 AM', checks: null } });
    expect(await screen.findByText('Chat needs the gateway')).toBeInTheDocument();
    expect(screen.getByText(/The gateway last answered today at 7:12 AM\./)).toBeInTheDocument();
    expect(screen.getByLabelText('Your question')).toBeDisabled();
    expect(screen.getByLabelText('Your question')).toHaveAttribute('placeholder', 'Paused until the gateway answers');
  });

  it('the budget: one line at 80%, and the used-up state with Change the budget for those who can', async () => {
    mount({ ...STATUS, budget: { ...STATUS.budget, warn: '$8.10 of this month’s $10 is used.' } });
    expect(await screen.findByText('$8.10 of this month’s $10 is used.')).toBeInTheDocument();
  });

  it('the used-up budget', async () => {
    const cap = "This month's chat budget of $10 is used up. Chat starts again on Nov 1, or sooner if a manager of Ours raises the budget in Settings → Chat.";
    mount({ ...STATUS, budget: { ...STATUS.budget, cap_line: cap } });
    expect(await screen.findByText(cap)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Change the budget' })).toHaveAttribute('href', '/b/ours/settings/chat');
    expect(screen.getByLabelText('Your question')).toBeDisabled();
  });

  it("a parent book's examples use the parent's name", async () => {
    mount(STATUS, { slug: 'margaret', name: 'Margaret Ellis', kind: 'parent', owners: [{ key: 'margaret', label: 'Margaret' }, { key: 'joint', label: 'Joint' }] });
    expect(await screen.findByRole('button', { name: "Is Margaret's supplement plan paid up?" })).toBeInTheDocument();
  });

  it('a 409 while asking turns into the off state', async () => {
    useFakeTimers();
    let on = true;
    stubFetch({
      '/api/chat': () => reply({ ...STATUS, on }), '/api/auth/me': ME,
      'POST /api/chat/preview': { text: 'How much is in savings?', as_written: true, chips: [], labels: {} },
      'POST /api/chat/ask': () => { on = false; return reply({ error: 'Chat is off for this book. A manager can turn it on in Settings → Chat.' }, 409); },
    });
    wrapBook(<Routes><Route path="/b/:slug/ask/*" element={<Ask />} /></Routes>, {}, '/b/ours/ask');
    fireEvent.change(await screen.findByLabelText('Your question'), { target: { value: 'How much is in savings?' } });
    await act(async () => { await vi.advanceTimersByTimeAsync(PREVIEW_DELAY_MS); });
    await screen.findByText('Claude will see your question as written.');
    fireEvent.click(screen.getByRole('button', { name: 'Send' }));
    expect(await screen.findByText('Chat is off for this book')).toBeInTheDocument();
  });
});

describe('the Ask tab with ?about= (Ask about this P24, P25)', () => {
  const DINING = { about: { kind: 'category', category: 'dining', month: '2026-10' }, sent: "It's about Eating out (category dining) in October 2026.", chips: [], labels: {} };
  const routes = <Routes><Route path="/b/:slug/ask/*" element={<Ask />} /></Routes>;
  beforeEach(() => {
    useFakeTimers();                         // the preview's 400 ms, driven by Testing Library's waits
    letTestingLibraryDriveFakeTimers();
    localStorage.clear();
    localStorage.setItem('steward-ask-tour:1', 'done');
    resetTourLoad();
    resetTourHidden();
  });

  it('shows the chip; ✕ drops it from the address and add back puts it there again; a question carries it', async () => {
    const fetchMock = stubFetch({ '/api/chat': STATUS, '/api/auth/me': ME, 'POST /api/chat/about': DINING,
      'POST /api/chat/preview': { text: 'Why?', as_written: true, chips: [], labels: {} },
      'POST /api/chat/ask': () => new Response('{"type":"conversation","id":7,"note":null,"turn_id":"t_1"}\n', { status: 200 }),
      '/api/chat/conversations/7': { id: 7, title: 'Why?', ended: false, requests: 0, long_line: null, labels: {}, turns: [] } });
    const { location } = renderAt(routes, {}, '/ask?about=category:dining:2026-10');
    await waitFor(() => expect(document.querySelector('.ask-chip')).toHaveTextContent('About: Eating out · October'));
    expect(document.querySelector('.willsend')).toHaveTextContent("It's about Eating out (category dining) in October 2026.");
    fireEvent.click(screen.getByRole('button', { name: 'Remove: About Eating out · October' }));
    await waitFor(() => expect(location.current.search).toBe(''));
    fireEvent.click(screen.getByRole('button', { name: 'Add back: About Eating out · October' }));
    await waitFor(() => expect(location.current.search).toBe('?about=category:dining:2026-10'));
    await waitFor(() => expect(document.querySelector('.ask-chip')).toHaveTextContent('About: Eating out · October'));
    fireEvent.change(screen.getByLabelText('Your question'), { target: { value: 'Why?' } });
    await screen.findByText('Claude will see your question as written.');
    fireEvent.click(screen.getByRole('button', { name: 'Send' }));
    await waitFor(() => expect(callsTo(fetchMock, 'POST', '/api/chat/ask')).toHaveLength(1));
    expect(callsTo(fetchMock, 'POST', '/api/chat/ask')[0].body).toEqual({ question: 'Why?', conversation_id: null, about: DINING.about });
    await waitFor(() => expect(location.current.pathname).toBe('/b/ours/ask/c/7'));
    expect(location.current.search).toBe('?about=category:dining:2026-10');      // a new conversation keeps the chip
  });

  it("Open in Ask's draft arrives in the box from the router's state, never the address", async () => {
    stubFetch({ '/api/chat': STATUS, '/api/auth/me': ME });
    renderAt(routes, {}, { pathname: '/ask', state: { draft: 'Is this higher than usual?' } });
    expect(await screen.findByLabelText('Your question')).toHaveValue('Is this higher than usual?');
  });

  it("a conversation's turns show what each was asked about", async () => {
    const TURN = { turn_id: 't_1', asked: 'Why?', sent: 'Why?', chips: [], as_written: true, who: 'JR', when: 'Today 9:41 AM', steps: [],
      answer: 'Yes.', stop: 'end_turn', line: null, meta: '3 seconds · $0.04', saw: [], approval: null, looked_into: false, unfinished: false,
      about: { chip: DINING.about, sent: DINING.sent } };
    stubFetch({ '/api/chat': STATUS, '/api/auth/me': ME,
      '/api/chat/conversations/7': { id: 7, title: 'Why?', ended: false, requests: 1, long_line: null, labels: {}, turns: [TURN] } });
    renderAt(routes, {}, '/ask/c/7');
    expect(await screen.findByText('About: Eating out · October')).toHaveClass('qabout');
  });

  it('a stale ?about= shows nothing or the gone line, and the question still goes', async () => {
    const fetchMock = stubFetch({ '/api/chat': STATUS, '/api/auth/me': ME,
      'POST /api/chat/about': () => reply({ error: "That isn't in this book any more." }, 404) });
    const stale = renderAt(routes, {}, '/ask?about=nickname:3');
    await screen.findByRole('heading', { name: 'Ask about Ours' });
    expect(document.querySelector('.ask-chip')).toBeNull();
    expect(callsTo(fetchMock, 'POST', '/api/chat/about')).toHaveLength(0);       // not P25's grammar: never asked
    stale.unmount();
    renderAt(routes, {}, '/ask?about=transaction:99999');
    expect(await screen.findByText("That isn't in this book any more.")).toBeInTheDocument();
    expect(screen.getByLabelText('Your question')).not.toBeDisabled();
  });

  const FAILED = { turn_id: 't_1', asked: 'Why?', sent: 'Why?', chips: [], as_written: true, who: 'JR', when: 'Today 9:41 AM', steps: [],
    answer: '', stop: 'busy', line: 'Claude is busy. Try again in a minute.', meta: null, saw: [], approval: null, looked_into: false,
    unfinished: false, about: { chip: DINING.about, sent: DINING.sent } };
  const SEVEN = { id: 7, title: 'Why?', ended: false, requests: 1, long_line: null, labels: {}, turns: [FAILED] };

  it('Ask again on a failed turn keeps the About, as Send does (Argon follow-up 7)', async () => {
    const fetchMock = stubFetch({ '/api/chat': STATUS, '/api/auth/me': ME, 'POST /api/chat/about': DINING,
      '/api/chat/conversations/7': SEVEN,
      'POST /api/chat/ask': () => new Response('{"type":"conversation","id":7,"note":null,"turn_id":"t_2"}\n', { status: 200 }) });
    renderAt(routes, {}, '/ask/c/7?about=category:dining:2026-10');
    await waitFor(() => expect(document.querySelector('.ask-chip')).toHaveTextContent('About: Eating out · October'));
    fireEvent.click(await screen.findByRole('button', { name: 'Ask again' }));
    await waitFor(() => expect(callsTo(fetchMock, 'POST', '/api/chat/ask')).toHaveLength(1));
    expect(callsTo(fetchMock, 'POST', '/api/chat/ask')[0].body).toEqual({ question: 'Why?', conversation_id: 7, about: DINING.about });
  });

  const ROWS = { conversations: [{ id: 8, title: 'Other', group: 'today', when: '9:02 AM', questions: 1, store_names: false, requests: 1 }] };
  const stubs = () => stubFetch({ '/api/chat': STATUS, '/api/auth/me': ME, 'POST /api/chat/about': DINING,
    '/api/chat/conversations/7': SEVEN, '/api/chat/conversations/8': { ...SEVEN, id: 8, title: 'Other', turns: [] },
    '/api/chat/conversations': ROWS });
  const chipShows = () => waitFor(() => expect(document.querySelector('.ask-chip')).toHaveTextContent('About: Eating out · October'));

  it('a trip to History and back keeps an unsent About as it was (Argon follow-up 6)', async () => {
    stubs();
    const { location } = renderAt(routes, {}, '/ask/c/7?about=category:dining:2026-10');
    await chipShows();
    fireEvent.click(screen.getByRole('button', { name: 'History' }));
    await waitFor(() => expect(location.current.pathname).toBe('/b/ours/ask/history'));
    fireEvent.click(screen.getByRole('button', { name: 'Back to the question' }));
    await waitFor(() => expect(location.current.pathname).toBe('/b/ours/ask/c/7'));
    expect(location.current.search).toBe('?about=category:dining:2026-10');
    await chipShows();
    expect(screen.queryByRole('button', { name: /^Add back/ })).toBeNull();
  });

  it('a removed About stays removed, with add back, through a trip to History', async () => {
    stubs();
    const { location } = renderAt(routes, {}, '/ask/c/7?about=category:dining:2026-10');
    await chipShows();
    fireEvent.click(screen.getByRole('button', { name: 'Remove: About Eating out · October' }));
    await waitFor(() => expect(location.current.search).toBe(''));
    fireEvent.click(screen.getByRole('button', { name: 'History' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Back to the question' }));
    await waitFor(() => expect(location.current.pathname).toBe('/b/ours/ask/c/7'));
    expect(await screen.findByRole('button', { name: 'Add back: About Eating out · October' })).toBeInTheDocument();
    expect(location.current.search).toBe('');
  });

  it('another conversation from History starts with no About and no add back (Argon follow-up 6)', async () => {
    stubs();
    const { location } = renderAt(routes, {}, '/ask/c/7?about=category:dining:2026-10');
    await chipShows();
    fireEvent.click(screen.getByRole('button', { name: 'History' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Other' }));
    await waitFor(() => expect(location.current.pathname).toBe('/b/ours/ask/c/8'));
    expect(location.current.search).toBe('');
    await screen.findByLabelText('Your question');
    expect(document.querySelector('.ask-chip')).toBeNull();
    expect(screen.queryByRole('button', { name: /^Add back/ })).toBeNull();
  });

  it('New starts with no About and no add back (Argon follow-up 6)', async () => {
    const fetchMock = stubs();
    const { location } = renderAt(routes, {}, '/ask/c/7?about=category:dining:2026-10');
    await chipShows();
    fireEvent.click(screen.getByRole('button', { name: 'New' }));
    await waitFor(() => expect(location.current.pathname).toBe('/b/ours/ask'));
    expect(location.current.search).toBe('');
    expect(document.querySelector('.ask-chip')).toBeNull();
    expect(screen.queryByRole('button', { name: /^Add back/ })).toBeNull();
    expect(callsTo(fetchMock, 'POST', '/api/chat/ask')).toHaveLength(0);
  });
});

describe('a Sample', () => {
  it('shows one line and asks the chat API nothing', async () => {
    const { fetchMock } = mount(STATUS, { sample: true });
    expect(await screen.findByText('Ask is off in the Sample.')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /Settings/ })).toBeNull();
    expect(fetchMock.mock.calls.filter(([u]) => /\/api\/(b\/[^/]+\/)?chat/.test(String(u)))).toEqual([]);
  });
});
