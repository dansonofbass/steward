import { fireEvent, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { setCurrentBook } from '../../api/book';
import { stubFetch, wrapBook } from '../../test-utils';
import { SentLog } from './SentLog';

afterEach(() => { vi.unstubAllGlobals(); setCurrentBook('ours'); });

const STATUS = { on: true, can_change: true, members: ['JR', 'Alex'], managers: ['JR', 'Alex'] };
const PAGE = {
  people: [{ id: 1, name: 'JR' }, { id: 2, name: 'Alex' }], next_offset: null,
  requests: [
    { key: 't_1.3', at: '2026-10-19T17:03:00+00:00', when: 'today at 10:03 AM', day: 'Today', who: 'JR', channel: 'Chat', what: '9 store rows, approved by JR', kind: 'store_rows', conversation: 'New subscriptions this year', size: '2 KB' },
    { key: 't_1.1', at: '2026-10-19T17:02:00+00:00', when: 'today at 10:02 AM', day: 'Today', who: 'JR', channel: 'Chat', what: 'Question', kind: 'question', conversation: 'New subscriptions this year', size: '1 KB' },
    { key: 't_0.1', at: '2026-10-18T20:00:00+00:00', when: 'Oct 18 at 1:00 PM', day: 'Sun, Oct 18', who: 'Alex', channel: 'Chat', what: '2 results: spending by category, money in and out', kind: 'results', conversation: 'Dining', size: '4 KB' },
  ],
};
const DETAIL = {
  key: 't_1.3', who: 'JR', when: 'today at 10:03 AM', approved_by: 'JR', conversation: 'New subscriptions this year', size: '2 KB',
  checks: ['The shape matches what Steward may send', 'No number longer than 4 digits', "The gateway's privacy check found no names", 'Nothing matches a name or number this book knows'],
  aliases: [{ alias: 'Account 2', label: 'Rewards Card ••4402' }],
  parts: [{ id: 9, part: 'merchant_rows', label: 'Store rows', sha256: 'ab'.repeat(32), bytes: 2048, payload: { content: { rows: [{ merchant: 'StreamBox', account: 'Account 2' }] } } }],
};

describe('Everything sent so far', () => {
  it('groups requests by day and opens one with its checks, aliases and exact JSON', async () => {
    stubFetch({ '/api/chat/sent/': DETAIL, '/api/chat/sent': PAGE, '/api/chat': STATUS });
    wrapBook(<SentLog />, {}, '/b/ours/settings/chat/sent');
    expect(await screen.findByText('Today · 2 requests')).toBeInTheDocument();
    expect(screen.getByText('Sun, Oct 18 · 1 request')).toBeInTheDocument();
    expect(screen.getByText("Everything sent from Ours to Anthropic, newest first. JR and Alex can read it, and it can't be edited or deleted, even when a conversation is.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /9 store rows, approved by JR/ }));
    const detail = await screen.findByRole('region', { name: '9 store rows, approved by JR' });
    expect(within(detail).getByText('Approved by')).toBeInTheDocument();
    expect(within(detail).getByText('No number longer than 4 digits')).toBeInTheDocument();
    expect(within(detail).getByText('Account 2 is Rewards Card ••4402')).toBeInTheDocument();
    expect(within(detail).getByText(/"merchant": "StreamBox"/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Download as a JSON file' })).toHaveAttribute('href', '/api/b/ours/chat/export');
  });

  it('filters by who and what', async () => {
    const fetchMock = stubFetch({ '/api/chat/sent': PAGE, '/api/chat': STATUS });
    wrapBook(<SentLog />, {}, '/b/ours/settings/chat/sent');
    await screen.findByText('Today · 2 requests');
    fireEvent.change(screen.getByLabelText('Who'), { target: { value: '2' } });
    fireEvent.change(screen.getByLabelText('What'), { target: { value: 'store_rows' } });
    await vi.waitFor(() => expect(fetchMock.mock.calls.some(([u]) => String(u) === '/api/b/ours/chat/sent?who=2&what=store_rows')).toBe(true));
  });

  it('opens the request named in the address', async () => {
    stubFetch({ '/api/chat/sent/': DETAIL, '/api/chat/sent': PAGE, '/api/chat': STATUS });
    wrapBook(<SentLog />, {}, '/b/ours/settings/chat/sent?open=t_1.3');
    expect(await screen.findByRole('region', { name: '9 store rows, approved by JR' })).toBeInTheDocument();
  });

  it('a viewer reads the log but gets no download', async () => {
    stubFetch({ '/api/chat/sent': PAGE, '/api/chat': { ...STATUS, can_change: false } });
    wrapBook(<SentLog />, { role: 'viewer' }, '/b/ours/settings/chat/sent');
    expect(await screen.findByText('Today · 2 requests')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Download as a JSON file' })).toBeNull();
  });

  it('reads the list and detail fields as the server shapes them', async () => {
    const page = { ...PAGE, requests: [{ ...PAGE.requests[1], conversation: null, kind: 'history' }, PAGE.requests[2]] };
    stubFetch({ '/api/chat/sent/': { ...DETAIL, approved_by: null, aliases: [] }, '/api/chat/sent': page, '/api/chat': STATUS });
    wrapBook(<SentLog />, {}, '/b/ours/settings/chat/sent');
    expect(await screen.findByText('Today · 1 request')).toBeInTheDocument();
    expect(screen.getByText('Dining')).toBeInTheDocument();
    const who = screen.getByLabelText('Who') as HTMLSelectElement;
    expect([...who.options].map((o) => o.textContent)).toEqual(['Everyone', 'JR', 'Alex']);
    fireEvent.click(screen.getByRole('button', { name: /Question/ }));
    const detail = await screen.findByRole('region', { name: 'Question' });
    expect(within(detail).queryByText('Approved by')).toBeNull();
    expect(within(detail).getByText('Asked by')).toBeInTheDocument();
    expect(within(detail).getByText('The gateway\'s privacy check found no names')).toBeInTheDocument();
    expect(within(detail).queryByText(/ is /)).toBeNull();
  });
});
