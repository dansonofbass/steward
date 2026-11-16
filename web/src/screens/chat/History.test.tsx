import { fireEvent, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { setCurrentBook } from '../../api/book';
import { callsTo, expectRemovalSaid, stubFetch, wrapBook } from '../../test-utils';
import { History } from './History';

afterEach(() => { vi.unstubAllGlobals(); setCurrentBook('ours'); });

const ROWS = { conversations: [
  { id: 3, title: 'New subscriptions this year', group: 'today', when: '10:02 AM', questions: 1, store_names: true, requests: 3 },
  { id: 2, title: 'Dining this year and last', group: 'today', when: '9:41 AM', questions: 2, store_names: false, requests: 4 },
  { id: 1, title: 'Cover a year on one income', group: 'week', when: 'Sun, Oct 18', questions: 3, store_names: false, requests: 6 },
] };

describe('your conversations', () => {
  it('groups by day with counts, store names and Delete', async () => {
    const onOpen = vi.fn();
    stubFetch({ '/api/chat/conversations': ROWS });
    wrapBook(<History onOpen={onOpen} />);
    expect(await screen.findByText('Today')).toBeInTheDocument();
    expect(screen.getByText('This week')).toBeInTheDocument();
    expect(screen.queryByText('Earlier')).toBeNull();
    expect(screen.getAllByText('Store names sent')).toHaveLength(1);
    expect(screen.getByText('2 questions')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Dining this year and last' }));
    expect(onOpen).toHaveBeenCalledWith(2);
    expect(screen.getByRole('link', { name: 'Everything sent so far' })).toHaveAttribute('href', '/b/ours/settings/chat/sent');
  });

  it('deleting asks first, says the log keeps what was sent, and takes the row off the list', async () => {
    const fetchMock = stubFetch({ '/api/chat/conversations': ROWS, 'DELETE /api/chat/conversations/2': { deleted: true } });
    wrapBook(<History onOpen={vi.fn()} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Delete Dining this year and last' }));
    const sheet = screen.getByRole('dialog');
    expect(within(sheet).getByText('Delete "Dining this year and last"?')).toBeInTheDocument();
    expect(sheet).toHaveTextContent("The 4 requests it sent stay in the book's log, because the log is never edited.");
    expect(callsTo(fetchMock, 'DELETE', '/api/chat/conversations')).toHaveLength(0);
    fireEvent.click(within(sheet).getByRole('button', { name: 'Delete' }));
    await vi.waitFor(() => expect(callsTo(fetchMock, 'DELETE', '/api/chat/conversations/2')).toHaveLength(1));
    await vi.waitFor(() => expect(screen.queryByRole('button', { name: 'Dining this year and last' })).toBeNull());
  });

  it('after deleting the last one, says so and focus stays on the line, though the list is gone (THO-1)', async () => {
    const one = { conversations: [ROWS.conversations[1]] };
    stubFetch({ '/api/chat/conversations': one, 'DELETE /api/chat/conversations/2': { deleted: true } });
    wrapBook(<History onOpen={vi.fn()} />);
    const button = await screen.findByRole('button', { name: 'Delete Dining this year and last' });
    button.focus();
    fireEvent.click(button);
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Delete' }));
    const line = 'Deleted "Dining this year and last".';
    await expectRemovalSaid(line, () => screen.getByText(line).closest('[aria-live]') as HTMLElement);
    expect(screen.getByText('No conversations yet. The questions you ask in Ours are listed here, newest first.')).toBeInTheDocument();
  });

  it('says so when there are none', async () => {
    stubFetch({ '/api/chat/conversations': { conversations: [] } });
    wrapBook(<History onOpen={vi.fn()} />);
    expect(await screen.findByText('No conversations yet. The questions you ask in Ours are listed here, newest first.')).toBeInTheDocument();
  });
});
