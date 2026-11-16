import { fireEvent, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { BookSummary } from '../../api/types';
import { expectRemovalSaid, reply, wrapBook } from '../../test-utils';
import { ClaudeCodeCard } from './ClaudeCode';

afterEach(() => { vi.unstubAllGlobals(); });

const OURS = { slug: 'ours', name: 'Ours', kind: 'household', role: 'manager', available: true, reason: null, owners: [], profile: null } as unknown as BookSummary;
const ACTIVE = { id: 7, person: 'Sam', issued_by: 'JR', issued: 'Oct 19', state: 'active', line: 'Until Nov 18 · not used yet', can_revoke: true };
const LIST = { grants: [ACTIVE], can_issue: true, days: 30 };
const GRANT = 'stg1.ours.' + 'A'.repeat(43);

function stub(routes: Record<string, unknown>) {
  const fn = vi.fn(async (url: string, init: RequestInit = {}) => {
    const r = routes[`${(init.method ?? 'GET').toUpperCase()} ${String(url)}`];
    if (r === undefined) return reply({ error: 'Not found.' }, 404);
    return typeof r === 'function' ? (r as (i: RequestInit) => Response)(init) : reply(r);
  });
  vi.stubGlobal('fetch', fn);
  return fn;
}

describe('Claude Code grants', () => {
  it('lists each grant with who, who issued it and until when', async () => {
    stub({ 'GET /api/b/ours/chat/grants': LIST });
    wrapBook(<ClaudeCodeCard book={OURS} />);
    expect(await screen.findByText('Sam · issued by JR, Oct 19')).toBeInTheDocument();
    expect(screen.getByText('Until Nov 18 · not used yet')).toBeInTheDocument();
  });

  it('issues a grant for the signed-in manager only and shows the command once', async () => {
    const fetchMock = stub({
      'GET /api/b/ours/chat/grants': LIST,
      'POST /api/b/ours/chat/grants': () => reply({ grant: GRANT, command: 'steward-gateway mcp-grant add', row: { ...ACTIVE, id: 8 } }),
    });
    const writeText = vi.fn(async () => {});
    vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } });
    wrapBook(<ClaudeCodeCard book={OURS} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Issue a grant' }));
    const sheet = screen.getByRole('dialog');
    expect(within(sheet).getByText('Claude Code grant for Ours')).toBeInTheDocument();
    expect(within(sheet).queryByLabelText('For')).toBeNull();
    expect(within(sheet).getByText('This grant is for you. Each manager issues their own.')).toBeInTheDocument();
    fireEvent.click(within(sheet).getByRole('button', { name: 'Issue a grant' }));
    expect(await within(sheet).findByText('steward-gateway mcp-grant add')).toBeInTheDocument();
    expect(within(sheet).getAllByText(GRANT)).toHaveLength(1);
    expect(within(sheet).getByText('Run the command in a plain terminal and paste the grant when it asks.')).toBeInTheDocument();
    expect(within(sheet).getByText('Copy this now. Steward shows it only once.')).toBeInTheDocument();
    const posted = fetchMock.mock.calls.find(([u, i]) => u === '/api/b/ours/chat/grants' && (i as RequestInit)?.method === 'POST');
    expect(JSON.parse(String((posted![1] as RequestInit).body))).toEqual({});
    fireEvent.click(within(sheet).getByRole('button', { name: 'Copy' }));
    await vi.waitFor(() => expect(writeText).toHaveBeenCalledWith(GRANT));
    await vi.waitFor(() => expect(within(sheet).getByText('Copied')).toHaveAttribute('role', 'status'));   // said beside the button (WEB-21)
    fireEvent.click(within(sheet).getByRole('button', { name: 'Done' }));
    await vi.waitFor(() => expect(screen.queryByText(GRANT)).toBeNull());
  });

  it('revokes after asking, says so, and keeps focus on the card, not the gone button (THO-1)', async () => {
    let list = LIST;
    const fetchMock = stub({
      'GET /api/b/ours/chat/grants': () => reply(list),
      'POST /api/b/ours/chat/grants/7/revoke': () => {
        const row = { ...ACTIVE, state: 'revoked', line: 'Revoked by JR, Oct 21', can_revoke: false };
        list = { ...LIST, grants: [row] };
        return reply({ row });
      },
    });
    wrapBook(<ClaudeCodeCard book={OURS} />);
    const button = await screen.findByRole('button', { name: "Revoke Sam's grant" });
    button.focus();
    fireEvent.click(button);
    const sheet = screen.getByRole('dialog');
    expect(within(sheet).getByText("Revoke Sam's grant for Ours?")).toBeInTheDocument();
    expect(within(sheet).getByText('Claude Code stops getting answers from Ours at once. Nothing in Ours changes, and a manager can issue a new grant.')).toBeInTheDocument();
    fireEvent.click(within(sheet).getByRole('button', { name: 'Revoke' }));
    await vi.waitFor(() => expect(fetchMock.mock.calls.some(([u]) => u === '/api/b/ours/chat/grants/7/revoke')).toBe(true));
    await expectRemovalSaid("Revoked Sam's grant for Ours.", () => screen.getByText("Revoked Sam's grant for Ours.").closest('[aria-live]') as HTMLElement);
    expect(await screen.findByText('Revoked by JR, Oct 21')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: "Revoke Sam's grant" })).toBeNull();
  });

  it("a viewer sees the list but can't issue", async () => {
    stub({ 'GET /api/b/ours/chat/grants': { ...LIST, can_issue: false, grants: [{ ...ACTIVE, can_revoke: false }] } });
    wrapBook(<ClaudeCodeCard book={OURS} />);
    expect(await screen.findByText('Sam · issued by JR, Oct 19')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Issue a grant' })).toBeNull();
    expect(screen.queryByRole('button', { name: /^Revoke/ })).toBeNull();
  });

  it('says so when a book has none', async () => {
    stub({ 'GET /api/b/ours/chat/grants': { ...LIST, grants: [] } });
    wrapBook(<ClaudeCodeCard book={OURS} />);
    expect(await screen.findByText('No Claude Code grants.')).toBeInTheDocument();
  });
});
