import { fireEvent, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { setCurrentBook } from '../../api/book';
import { reply, wrapBook } from '../../test-utils';
import ChatSettings from './ChatSettings';
import { setGatewayName } from '../../lib/gatewayName';

afterEach(() => { vi.unstubAllGlobals(); setCurrentBook('ours'); });

const DISCLOSURE = 'Steward sends Claude, an AI made by Anthropic, the numbers it needs to answer you: balances, income, spending totals, holdings, debts, ages, your state and tax facts.';
const BASE = {
  seen: true, disclosure: DISCLOSURE, off_line: 'Chat is off for this book. A manager can turn it on in Settings → Chat.',
  gateway: { state: 'ok', line: 'The gateway is answering.', last_answered: 'today at 10:04 AM', checked: 'today at 10:04 AM', checks: { redaction: true, key: true, categorizer: false }, away_long: false },
  budget: { line: 'This month: $3.12 of $10 · 26 questions', warn: null, cap_line: null, spent_cents: 312, cap_cents: 1000, questions: 26, model: 'claude-opus-5-5' },
  models: [{ id: 'claude-opus-5-5', label: 'Claude Opus 5.5 (the default)' }, { id: 'claude-sonnet-5-5', label: 'Claude Sonnet 5.5 (about half the cost)' }],
};
const OURS = { ...BASE, on: true, can_change: true, can_budget: true, changed: { by: 'JR', at: '', line: 'Turned on by JR, Oct 19' }, members: ['JR', 'Alex'], managers: ['JR', 'Alex'], sent_month: { requests: 41, last: 'today at 10:03 AM' } };
const MARGARET = { ...BASE, on: false, can_change: true, can_budget: false, changed: null, members: ['JR', 'Alex', 'Dana'], managers: ['JR', 'Alex'], sent_month: { requests: 0, last: null } };
const book = (slug: string, name: string, kind: string, role = 'manager') => ({ slug, name, kind, role, available: true, reason: null, owners: [], profile: null });
const ME = { user: { id: 1, username: 'jr', display_name: 'JR' }, session: { id: 1, device_label: 'Phone', created_at: '' },
  books: [book('ours', 'Ours', 'household'), book('margaret', 'Margaret Ellis', 'parent')] };
const USAGE = { usage: { months: [{ month: 'Oct 2026', spent: '$3.12', questions: 26 }, { month: 'Sep 2026', spent: '$4.40', questions: 31 }],
  by_book: [{ book: 'Ours', spent: '$2.41', questions: 19 }, { book: 'Margaret Ellis', spent: '$0.71', questions: 7 }],
  by_person: [{ book: 'Ours', person: 'JR', spent: '$1.62', questions: 13 }] } };

/** Routes by the exact address the browser asks for, so two books' statuses can differ. */
function stubRaw(routes: Record<string, unknown>) {
  const fn = vi.fn(async (url: string, init: RequestInit = {}) => {
    const r = routes[`${(init.method ?? 'GET').toUpperCase()} ${String(url).split('?')[0]}`];
    if (r === undefined) return reply({ error: 'Not found.' }, 404);
    return typeof r === 'function' ? (r as (i: RequestInit) => Response)(init) : reply(r);
  });
  vi.stubGlobal('fetch', fn);
  return fn;
}
const ROUTES = { 'GET /api/auth/me': ME, 'GET /api/b/ours/chat': OURS, 'GET /api/b/margaret/chat': MARGARET, 'GET /api/b/ours/chat/usage': USAGE,
  'GET /api/b/ours/chat/grants': { grants: [], can_issue: true, days: 30 },
  'GET /api/b/margaret/chat/grants': { grants: [], can_issue: true, days: 30 } };

describe('Settings → Chat, pairing', () => {
  const unpaired = (url_set: boolean) => ({ ...OURS, gateway: { ...OURS.gateway, state: 'not_set_up', line: 'Not paired.', paired: false, url_set } });
  it('shows the pairing form to a household manager when a URL is set and nothing is paired', async () => {
    stubRaw({ ...ROUTES, 'GET /api/b/ours/chat': unpaired(true) });
    wrapBook(<ChatSettings />);
    expect(await screen.findByLabelText('Code')).toBeInTheDocument();
  });
  it('shows no form when there is no gateway URL', async () => {
    stubRaw({ ...ROUTES, 'GET /api/b/ours/chat': unpaired(false) });
    wrapBook(<ChatSettings />);
    expect(await screen.findByText('Not paired.')).toBeInTheDocument();
    expect(screen.queryByLabelText('Code')).toBeNull();
  });
});

describe('Settings → Chat', () => {
  it('names the gateway the way /me does (spec 2026-11-05, section 7)', async () => {
    setGatewayName('Zebra-Box');
    stubRaw(ROUTES);
    wrapBook(<ChatSettings />);
    expect(await screen.findByRole('heading', { name: 'Zebra-Box' })).toBeInTheDocument();
    expect(screen.getByText('Zebra-Box is answering')).toBeInTheDocument();
  });

  it('the lede names the store and payee names a manager approves, and that the gateway can miss a name (16d)', async () => {
    stubRaw(ROUTES);
    wrapBook(<ChatSettings />);
    expect(await screen.findByText("Ask Claude about a book's money. Steward sends figures, not the account numbers and names it holds, except store and payee names a manager approves. Your gateway looks for other names and can miss one. Each part sent is logged.")).toBeInTheDocument();
  });
  it("shows the gateway's checks and how to stop chat without Steward", async () => {
    stubRaw(ROUTES);
    wrapBook(<ChatSettings />);
    expect(await screen.findByText('The gateway is answering')).toBeInTheDocument();
    expect(screen.getByText('Privacy check is loaded')).toBeInTheDocument();
    // THO-2: a failed check says so in words; the cross beside it is hidden from a screen reader.
    expect(screen.getByText("Categorizer isn't answering").closest('li')).toHaveClass('is-off');
    expect(screen.queryByText('Categorizer is answering')).toBeNull();
    const lines = screen.getAllByRole('listitem').filter((li) => li.closest('ul.checks')).map((li) => li.textContent);
    expect(lines).toEqual(['Privacy check is loaded', 'The Claude key works', "Categorizer isn't answering"]);
    const cmd = screen.getByText('steward-gateway stop-chat');
    expect(cmd.tagName).toBe('CODE');
    expect(cmd.parentElement?.textContent).toBe('Checked today at 10:04 AM. To stop all chat without opening Steward, run steward-gateway stop-chat on the gateway.');
  });

  it('lists every book with its people, and turns one on only after the disclosure', async () => {
    const fetchMock = stubRaw({ ...ROUTES, 'POST /api/b/margaret/chat/on': () => reply({ ...MARGARET, on: true }) });
    wrapBook(<ChatSettings />);
    expect(await screen.findByRole('switch', { name: 'Chat in Ours' })).toHaveAttribute('aria-checked', 'true');
    expect(screen.getByText('Household · JR and Alex, managers · Turned on by JR, Oct 19')).toBeInTheDocument();
    const sw = await screen.findByRole('switch', { name: 'Chat in Margaret Ellis' });
    expect(screen.getByText('Parent · JR and Alex, managers; Dana, viewer')).toBeInTheDocument();
    fireEvent.click(sw);
    const sheet = screen.getByRole('dialog');
    // The disclosure comes first: the switch alone sends nothing (final review, Task 17).
    expect(fetchMock.mock.calls.some(([u]) => u === '/api/b/margaret/chat/on')).toBe(false);
    expect(within(sheet).getByText('Turn on chat in Margaret Ellis?')).toBeInTheDocument();
    expect(sheet).toHaveTextContent('JR, Alex and Dana will each see this once, the first time they open Ask in this book.');
    expect(sheet).toHaveTextContent("Dana can ask but can't approve store names.");
    fireEvent.click(within(sheet).getByRole('button', { name: 'Turn on' }));
    await vi.waitFor(() => expect(fetchMock.mock.calls.some(([u, i]) => u === '/api/b/margaret/chat/on' && JSON.parse(String((i as RequestInit).body)).on === true)).toBe(true));
    await vi.waitFor(() => expect(screen.getByRole('switch', { name: 'Chat in Margaret Ellis' })).toHaveAttribute('aria-checked', 'true'));
  });

  it.each([
    [['Alex', 'Dana'], 'Alex and Dana will each see this once, the first time they open Ask in this book.'],
    [['Alex'], 'Alex will see this once, the first time they open Ask in this book.'],
    [[], null],
  ])('the disclosure names the others who will see it, in the right number (INS-18): %j', (others, line) => {
    stubRaw({ ...ROUTES, 'GET /api/b/margaret/chat': { ...MARGARET, others } });
    wrapBook(<ChatSettings />);
    return screen.findByRole('switch', { name: 'Chat in Margaret Ellis' }).then((sw) => {
      fireEvent.click(sw);
      const sheet = screen.getByRole('dialog');
      if (line) expect(sheet).toHaveTextContent(line);
      else expect(sheet).not.toHaveTextContent('see this once');
      expect(sheet).not.toHaveTextContent('JR will');
    });
  });

  it('a reply that lands after the person switched books is not written into the other book', async () => {
    let release: () => void = () => {};
    const gate = new Promise<void>((r) => { release = r; });
    const off = { ...OURS, on: false, changed: null };
    stubRaw({ ...ROUTES, 'GET /api/b/ours/chat': off, 'POST /api/b/ours/chat/on': async () => { await gate; return reply({ ...OURS }); } });
    setCurrentBook('ours');
    const { qc } = wrapBook(<ChatSettings />);
    const write = vi.spyOn(qc, 'setQueryData');
    fireEvent.click(await screen.findByRole('switch', { name: 'Chat in Ours' }));
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Turn on' }));
    setCurrentBook('margaret');
    release();
    await vi.waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(write).not.toHaveBeenCalledWith(['chat', 'status'], expect.anything());
    expect(write).not.toHaveBeenCalledWith(['chat', 'status-of', 'ours'], expect.anything());
  });

  it('links each book’s log with this month’s requests', async () => {
    stubRaw(ROUTES);
    wrapBook(<ChatSettings />);
    expect(await screen.findByRole('link', { name: /Ours: 41 requests this month/ })).toHaveAttribute('href', '/b/ours/settings/chat/sent');
    expect(await screen.findByRole('link', { name: /Margaret Ellis: 0 requests this month/ })).toHaveAttribute('href', '/b/margaret/settings/chat/sent');
  });

  it('shows the budget with a meter, the pace and the split, and saves it', async () => {
    const fetchMock = stubRaw({ ...ROUTES, 'POST /api/b/ours/chat/budget': { ok: true } });
    wrapBook(<ChatSettings />);
    expect(await screen.findByRole('img', { name: '31% of the budget used' })).toBeInTheDocument();
    expect(screen.getByText(/^At this pace .* ends near \$/)).toBeInTheDocument();
    expect(await screen.findByRole('cell', { name: 'Margaret Ellis' })).toBeInTheDocument();
    expect(screen.getByRole('cell', { name: 'JR' })).toBeInTheDocument();
    expect(screen.getByText('Sep 2026')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Budget a month, in dollars'), { target: { value: '25' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await vi.waitFor(() => expect(fetchMock.mock.calls.some(([u, i]) => u === '/api/b/ours/chat/budget'
      && JSON.stringify(JSON.parse(String((i as RequestInit).body))) === JSON.stringify({ cap_dollars: 25, model: 'claude-opus-5-5' }))).toBe(true));
  });

  it('a name in two books says which book each row is, and sits under its book', async () => {
    const usage = { usage: { ...USAGE.usage, by_person: [{ book: 'Ours', person: 'JR', spent: '$1.62', questions: 13 },
      { book: 'Ours', person: 'Alex', spent: '$0.79', questions: 6 }, { book: 'Margaret Ellis', person: 'JR', spent: '$0.71', questions: 7 }] } };
    stubRaw({ ...ROUTES, 'GET /api/b/ours/chat/usage': usage });
    wrapBook(<ChatSettings />);
    expect(await screen.findByRole('cell', { name: 'JR · Ours' })).toBeInTheDocument();
    expect(screen.getByRole('cell', { name: 'JR · Margaret Ellis' })).toBeInTheDocument();
    expect(screen.getByRole('cell', { name: 'Alex' })).toBeInTheDocument();       // a name in one book needs no book
    const firsts = screen.getAllByRole('row').slice(1).map((r) => within(r).getAllByRole('cell')[0].textContent);
    expect(firsts).toEqual(['Ours', 'JR · Ours', 'Alex', 'Margaret Ellis', 'JR · Margaret Ellis']);
  });

  it('a household manager picks the model, saved at once; others only read it', async () => {
    const fetchMock = stubRaw({ ...ROUTES, 'POST /api/b/ours/chat/budget': { ok: true } });
    wrapBook(<ChatSettings />);
    fireEvent.click(await screen.findByRole('radio', { name: /Claude Sonnet 5.5/ }));
    await vi.waitFor(() => expect(fetchMock.mock.calls.some(([u, i]) => u === '/api/b/ours/chat/budget'
      && JSON.parse(String((i as RequestInit).body)).model === 'claude-sonnet-5-5')).toBe(true));
  });

  it('a viewer sees the state and the model without switches, the form or the radios', async () => {
    stubRaw({ ...ROUTES, 'GET /api/b/ours/chat': { ...OURS, can_change: false, can_budget: false }, 'GET /api/auth/me': { ...ME, books: [book('ours', 'Ours', 'household', 'viewer')] } });
    wrapBook(<ChatSettings />, { role: 'viewer' });
    expect(await screen.findByText('Household · JR and Alex, managers · Turned on by JR, Oct 19')).toBeInTheDocument();
    expect(screen.queryByRole('switch')).toBeNull();
    expect(screen.queryByLabelText('Budget a month, in dollars')).toBeNull();
    expect(screen.queryByRole('radio')).toBeNull();
    expect(screen.getByText('Claude Opus 5.5')).toBeInTheDocument();
  });

  it("says when the gateway isn't answering", async () => {
    stubRaw({ ...ROUTES, 'GET /api/b/ours/chat': { ...OURS, gateway: { ...BASE.gateway, state: 'away', checks: null, last_answered: 'today at 7:12 AM' }, budget: null } });
    wrapBook(<ChatSettings />);
    expect(await screen.findByText("The gateway isn't answering")).toBeInTheDocument();
    expect(screen.getByText("Last answered today at 7:12 AM. Chat and categorization are paused until it's back; nothing is sent another way.")).toBeInTheDocument();
    expect(screen.getByText('Spending shows here when the gateway answers.')).toBeInTheDocument();
  });

  it('says where PDFs are read', async () => {
    stubRaw({ ...ROUTES, 'GET /api/b/ours/chat': { ...OURS, gateway: { ...OURS.gateway, pdf_place: 'gateway' } } });
    wrapBook(<ChatSettings />);
    expect(await screen.findByText('PDFs are read on the gateway')).toBeInTheDocument();
  });

  it('says so when Steward reads them itself', async () => {
    stubRaw({ ...ROUTES, 'GET /api/b/ours/chat': { ...OURS, gateway: { ...OURS.gateway, pdf_place: 'local' } } });
    wrapBook(<ChatSettings />);
    expect(await screen.findByText('PDFs are read on Steward')).toBeInTheDocument();
  });

  it('has a Claude Code section with a card per book', async () => {
    stubRaw(ROUTES);
    wrapBook(<ChatSettings />);
    expect(await screen.findByRole('heading', { name: 'Claude Code' })).toBeInTheDocument();
    await vi.waitFor(() => expect(screen.getAllByText('No Claude Code grants.')).toHaveLength(2));
  });

  it('hides Claude Code when the gateway has it off (release spec, section 6)', async () => {
    stubRaw({ ...ROUTES, 'GET /api/b/ours/chat': { ...OURS, gateway: { ...OURS.gateway, mcp: false } } });
    wrapBook(<ChatSettings />);
    expect(await screen.findByText('The gateway is answering')).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Claude Code' })).toBeNull();
  });

  it('keeps Claude Code while the gateway is away or older, so a grant can still be revoked', async () => {
    stubRaw({ ...ROUTES, 'GET /api/b/ours/chat': { ...OURS, gateway: { ...OURS.gateway, mcp: null } } });
    wrapBook(<ChatSettings />);
    expect(await screen.findByRole('heading', { name: 'Claude Code' })).toBeInTheDocument();
  });
});
