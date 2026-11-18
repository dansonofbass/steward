import { fireEvent, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { setCurrentBook } from '../../api/book';
import { callsTo, reply, stubFetch, wrapBook } from '../../test-utils';
import type { Card } from './askApi';
import { ApprovalCard, ViewerCard } from './ApprovalCard';

afterEach(() => { vi.unstubAllGlobals(); setCurrentBook('ours'); });

const CARD: Card = {
  call_id: 'toolu_m1', reason: 'Totals show 5 new monthly payments this year but not what they are.', count: 2,
  first: 'Sep 18', last: 'Oct 18', names: [{ name: 'StreamBox', count: 2 }],
  rows: [{ date: 'Oct 18', store: 'StreamBox', amount_cents: -1599, category: 'subscriptions', account: 'Account 2' },
         { date: 'Sep 18', store: 'StreamBox', amount_cents: -1599, category: 'subscriptions', account: 'Account 2' }],
  payees: [], accounts: [{ alias: 'Account 2', label: 'Rewards Card ••4402' }], until: '10:12 AM', more: false, hash: 'h_card1',
};

describe('the store-names card', () => {
  it('shows why, the names with counts, every row and who each account is', () => {
    wrapBook(<ApprovalCard turnId="t_1" card={CARD} />);
    const card = screen.getByRole('group', { name: 'Claude asks for store names' });
    expect(card).toHaveTextContent('Totals show 5 new monthly payments this year but not what they are. Claude asks for these 2 rows, from Sep 18 to Oct 18.');
    expect(card.querySelector('.name')).toHaveTextContent('StreamBox 2');
    expect(within(card).getAllByRole('row')).toHaveLength(3);
    expect(card).toHaveTextContent('$15.99');
    expect(card).toHaveTextContent('Account 2 is Rewards Card ••4402; Claude gets only the alias.');
    expect(card).toHaveTextContent('Without an answer by 10:12 AM, Claude stops and nothing is sent.');
  });

  it('approves for this conversation only through the approvals route', async () => {
    const fetchMock = stubFetch({ 'POST /api/chat/approvals': { ok: true } });
    wrapBook(<ApprovalCard turnId="t_1" card={CARD} />);
    fireEvent.click(screen.getByRole('button', { name: 'Approve for this conversation' }));
    await vi.waitFor(() => expect(callsTo(fetchMock, 'POST', '/api/chat/approvals')[0]?.body).toEqual({ turn_id: 't_1', call_id: 'toolu_m1', send: true, hash: 'h_card1', ticked: [] }));
    await vi.waitFor(() => expect(screen.getByRole('button', { name: 'Approve for this conversation' })).toBeDisabled());
  });

  it("Don't send declines, and a card nobody is waiting for says so", async () => {
    const fetchMock = stubFetch({ 'POST /api/chat/approvals': () => reply({ error: "That question isn't waiting for an OK." }, 404) });
    wrapBook(<ApprovalCard turnId="t_1" card={CARD} />);
    fireEvent.click(screen.getByRole('button', { name: "Don't send" }));
    expect(await screen.findByText("That question isn't waiting for an OK.")).toBeInTheDocument();
    expect(callsTo(fetchMock, 'POST', '/api/chat/approvals')[0]?.body).toEqual({ turn_id: 't_1', call_id: 'toolu_m1', send: false, hash: 'h_card1', ticked: [] });
  });

  it('a transfer to a person goes as [name]; ticking the row sends the name the card shows, and only that row (issue #1)', async () => {
    const zelle: Card = {
      ...CARD, count: 3, names: [{ name: 'Zelle to [name]', count: 2 }, { name: 'StreamBox', count: 1 }],
      rows: [{ date: 'Oct 19', store: 'Zelle to [name]', amount_cents: -2500, category: 'gifts', account: 'Account 2', full: 'Zelle to Priya Nair' },
             { date: 'Oct 18', store: 'StreamBox', amount_cents: -1599, category: 'subscriptions', account: 'Account 2', full: null }],
      payees: [{ payee: 'Payee 4', name: 'Zelle to [name]', full: 'Zelle to Priya Nair' }],
    };
    const fetchMock = stubFetch({ 'POST /api/chat/approvals': { ok: true } });
    wrapBook(<ApprovalCard turnId="t_1" card={zelle} />);
    const card = screen.getByRole('group', { name: 'Claude asks for store names' });
    const boxes = within(card).getAllByRole('checkbox', { name: /^Send this name too/ });
    expect(boxes).toHaveLength(2);                                    // the Zelle row and the payee, not StreamBox
    expect(boxes[0]).toHaveAccessibleName('Send this name too (Zelle to Priya Nair)');
    expect(boxes[0]).not.toBeChecked();
    const firstRow = within(card).getAllByRole('row')[1];
    expect(within(firstRow).getByText('Zelle to [name]')).toBeInTheDocument();
    fireEvent.click(boxes[0]);
    expect(within(firstRow).getByText('Zelle to Priya Nair', { selector: '.strong' })).toBeInTheDocument();
    expect([...card.querySelectorAll('.name')].map((n) => n.textContent)).toEqual(['Zelle to Priya Nair 1', 'StreamBox 1', 'Zelle to [name] 1']);
    fireEvent.click(screen.getByRole('button', { name: 'Approve for this conversation' }));
    await vi.waitFor(() => expect(callsTo(fetchMock, 'POST', '/api/chat/approvals')[0]?.body).toEqual(
      { turn_id: 't_1', call_id: 'toolu_m1', send: true, hash: 'h_card1', ticked: ['r0'] }));
  });

  it("a viewer's card has no buttons and names the managers", () => {
    wrapBook(<ViewerCard managers={['JR', 'Alex']} where="Look into" />, { role: 'viewer', kind: 'parent' });
    expect(screen.getByText("Store and payee names need a manager's OK. Claude will answer from totals.")).toBeInTheDocument();
    expect(screen.getByText('JR or Alex can see the names in Look into, or ask the same question and approve them.')).toBeInTheDocument();
    expect(screen.queryByRole('button')).toBeNull();
  });
});
