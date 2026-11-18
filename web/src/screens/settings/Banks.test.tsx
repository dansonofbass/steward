import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { callsTo, expectRemovalSaid, reply, stubFetch, wrap, wrapBook } from '../../test-utils';
import { ACCTS } from '../accounts/fixtures';
import Banks from './Banks';

afterEach(() => vi.unstubAllGlobals());

describe('Banks card', () => {
  it('unlinking asks first and says the accounts and transactions stay', async () => {
    const fetchMock = stubFetch({
      '/api/simplefin': { linked: true, last_sync_at: null, last_error: null },
      '/api/institutions': { institutions: [] }, '/api/accounts': { accounts: [] },
      'DELETE /api/simplefin': () => new Response(null, { status: 204 }),
    });
    wrap(<Banks />);
    fireEvent.click(await screen.findByRole('button', { name: 'Unlink' }));
    const ask = screen.getByRole('dialog', { name: 'Unlink SimpleFIN?' });
    expect(within(ask).getByText('Your accounts and transactions stay; syncing stops. To start again, paste a new setup token.')).toBeInTheDocument();
    expect(callsTo(fetchMock, 'DELETE', '/api/simplefin')).toHaveLength(0);
    fireEvent.click(within(ask).getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByRole('dialog')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Unlink' }));
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Unlink' }));
    await waitFor(() => expect(callsTo(fetchMock, 'DELETE', '/api/simplefin')).toHaveLength(1));
  });
  it('after unlinking, says so and keeps focus on the card, where Unlink was (THO-1)', async () => {
    let status = { linked: true, last_sync_at: null, last_error: null };
    stubFetch({
      '/api/simplefin': () => reply(status),
      '/api/institutions': { institutions: [] }, '/api/accounts': { accounts: [] },
      'DELETE /api/simplefin': () => { status = { linked: false, last_sync_at: null, last_error: null }; return new Response(null, { status: 204 }); },
    });
    wrap(<Banks />);
    const button = await screen.findByRole('button', { name: 'Unlink' });
    button.focus();
    fireEvent.click(button);
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Unlink' }));
    await expectRemovalSaid('SimpleFIN is unlinked.', () => screen.getByRole('heading', { name: 'SimpleFIN' }));
    expect(screen.queryByRole('button', { name: 'Unlink' })).toBeNull();
  });
  it('says what SimpleFIN covers and links to the import screen when linked', async () => {
    stubFetch({
      '/api/simplefin': { linked: true, last_sync_at: null, last_error: null },
      '/api/institutions': { institutions: [] }, '/api/accounts': { accounts: [] },
    });
    wrap(<Banks />);
    expect(await screen.findByText(/SimpleFIN brings in the last 90 days when you first link it; a bank you add later starts with its last 45 days\. For older history, import a file from your bank\./)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Import files' })).toHaveAttribute('href', '/b/ours/settings/import');
  });
  it('leaves the line out when not linked', async () => {
    stubFetch({
      '/api/simplefin': { linked: false, last_sync_at: null, last_error: null },
      '/api/institutions': { institutions: [] }, '/api/accounts': { accounts: [] },
    });
    wrap(<Banks />);
    await screen.findByText('Not linked');
    expect(screen.queryByText(/last 90 days/)).toBeNull();
  });
});

describe('Banks and accounts', () => {
  it('is headed Banks and accounts and lists the accounts updated manually, each with Update balance', async () => {
    stubFetch({
      '/api/simplefin': { linked: true, last_sync_at: null, last_error: null },
      '/api/institutions': { institutions: [] }, '/api/accounts': { accounts: ACCTS },
    });
    wrap(<Banks />, '/b/ours/settings/banks');
    expect(screen.getByRole('heading', { level: 2, name: 'Banks and accounts' })).toBeInTheDocument();
    const manual = (await screen.findByRole('heading', { level: 3, name: 'Updated manually' })).closest('section')!;
    expect(await within(manual).findByText('House')).toBeInTheDocument();
    expect(within(manual).queryByText('Checking ••6789')).toBeNull();
    expect(within(manual).getByRole('button', { name: 'Update balance' })).toHaveAccessibleDescription('House');
    fireEvent.click(within(manual).getByRole('button', { name: 'Update balance' }));
    expect(screen.getByRole('dialog', { name: 'Update House' })).toBeInTheDocument();
  });
  it("a parent book's manager gets no Updated manually: the server keeps those for households", async () => {
    stubFetch({
      '/api/simplefin': { linked: true, last_sync_at: null, last_error: null },
      '/api/institutions': { institutions: [] }, '/api/accounts': { accounts: ACCTS },
    });
    wrapBook(<Banks />, { slug: 'mom', kind: 'parent' }, '/b/mom/settings/banks');
    await screen.findByRole('button', { name: 'Unlink' });
    expect(screen.queryByRole('heading', { name: 'Updated manually' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Add account' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Update balance' })).toBeNull();
  });
  it('says when there are none', async () => {
    stubFetch({
      '/api/simplefin': { linked: true, last_sync_at: null, last_error: null },
      '/api/institutions': { institutions: [] }, '/api/accounts': { accounts: [ACCTS[0]] },
    });
    wrap(<Banks />, '/b/ours/settings/banks');
    expect(await screen.findByText('No accounts updated manually yet.')).toBeInTheDocument();
  });
});

describe('a bank that needs a sign-in (issue 16)', () => {
  const inst = (id: number, name: string, last_error: string | null = null) =>
    ({ id, name, source: 'simplefin', last_sync_at: null, last_error, account_count: 2 });

  it('names the bank, gives the step, and marks its line', async () => {
    stubFetch({
      '/api/simplefin': { linked: true, last_sync_at: null, last_error: null, sign_in: ['Big Bank'] },
      '/api/institutions': { institutions: [inst(1, 'Big Bank'), inst(2, 'Savings Bank')] }, '/api/accounts': { accounts: [] },
    });
    wrap(<Banks />);
    const need = await screen.findByTestId('sign-in-needed');
    expect(need).toHaveTextContent('Big Bank needs you to sign in again at SimpleFIN.');
    expect(need).toHaveTextContent('Sign in again at SimpleFIN Bridge, then choose Update now.');
    const marked = screen.getAllByTestId('bank-needs-sign-in');
    expect(marked).toHaveLength(1);
    expect(marked[0].closest('li')).toHaveTextContent('Big Bank');
    expect(marked[0]).toHaveTextContent('Needs a sign-in');
    expect(screen.getAllByText(/needs you to sign in again/)).toHaveLength(1);   // the notice says it, the line doesn't
    expect(screen.getByRole('button', { name: 'Update now' })).toBeInTheDocument();
  });

  it("a bank whose last error says the same words isn't said twice on the page", async () => {
    stubFetch({
      '/api/simplefin': { linked: true, last_sync_at: null, last_error: null, sign_in: ['Big Bank'] },
      '/api/institutions': { institutions: [inst(1, 'Big Bank', 'Big Bank needs you to sign in again at SimpleFIN')] },
      '/api/accounts': { accounts: [] },
    });
    wrap(<Banks />);
    const line = (await screen.findByTestId('bank-needs-sign-in')).closest('li')!;
    expect(within(line).queryByText(/needs you to sign in again/)).toBeNull();
    expect(within(line).getByText(/Needs a sign-in/)).toBeInTheDocument();
    expect(screen.getAllByText(/needs you to sign in again/)).toHaveLength(1);
  });

  it('when SimpleFIN is unlinked, the step is to link it again', async () => {
    stubFetch({
      '/api/simplefin': { linked: false, last_sync_at: null, last_error: null, sign_in: ['Big Bank'] },
      '/api/institutions': { institutions: [] }, '/api/accounts': { accounts: [] },
    });
    wrap(<Banks />);
    expect(await screen.findByTestId('sign-in-needed')).toHaveTextContent('Sign in again at SimpleFIN Bridge, then link SimpleFIN with a new setup token.');
  });

  it('nothing is said when no bank needs one', async () => {
    stubFetch({
      '/api/simplefin': { linked: true, last_sync_at: null, last_error: null, sign_in: [] },
      '/api/institutions': { institutions: [inst(1, 'Big Bank')] }, '/api/accounts': { accounts: [] },
    });
    wrap(<Banks />);
    await screen.findByText('Big Bank');
    expect(screen.queryByTestId('sign-in-needed')).toBeNull();
    expect(screen.queryByTestId('bank-needs-sign-in')).toBeNull();
  });
});
