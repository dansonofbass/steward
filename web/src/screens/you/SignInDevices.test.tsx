import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { callsTo, expectRemovalSaid, reply, stubFetch, wrap } from '../../test-utils';
import SignInDevices from './SignInDevices';

afterEach(() => vi.unstubAllGlobals());
const ME = { user: { id: 1, username: 'jr', display_name: 'JR' }, session: { id: 10, device_label: 'JR’s laptop', created_at: '2026-10-01T00:00:00Z' }, books: [] };
const USERS = { users: [{ id: 1, username: 'jr', display_name: 'JR', can_reset: false }, { id: 2, username: 'sam', display_name: 'Sam', can_reset: true }] };
const PASSKEYS = { passkeys: [{ id: 4, label: 'iPhone', created_at: '2026-10-02T00:00:00Z' }] };
const SESSIONS = { sessions: [
  { id: 10, device_label: 'JR’s laptop', created_at: '2026-10-01T00:00:00Z', last_seen_at: '2026-10-25T00:00:00Z' },
  { id: 11, device_label: 'iPhone', created_at: '2026-10-02T00:00:00Z', last_seen_at: '2026-10-24T00:00:00Z' }] };
const ROUTES = { '/api/auth/me': ME, '/api/users': USERS, '/api/auth/passkeys': PASSKEYS, '/api/auth/sessions': SESSIONS };

describe('Sign-in and devices', () => {
  it('removing a passkey asks first and says the password still works', async () => {
    const fetchMock = stubFetch({ ...ROUTES, 'DELETE /api/auth/passkeys/4': () => new Response(null, { status: 204 }) });
    wrap(<SignInDevices />);
    fireEvent.click(await screen.findByRole('button', { name: 'Remove iPhone' }));
    const ask = screen.getByRole('dialog', { name: 'Remove the passkey iPhone?' });
    expect(within(ask).getByText('That device can no longer sign in with its passkey. Your password still works everywhere, and nothing is signed out.')).toBeInTheDocument();
    expect(callsTo(fetchMock, 'DELETE', '/api/auth/passkeys')).toHaveLength(0);
    fireEvent.click(within(ask).getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByRole('dialog')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Remove iPhone' }));
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Remove' }));
    await waitFor(() => expect(callsTo(fetchMock, 'DELETE', '/api/auth/passkeys/4')).toHaveLength(1));
  });
  it('after removing a passkey, tells this device which passkeys still sign in (issue #13)', async () => {
    const accepted = { rp_id: 'nas.example.ts.net', user_id: 'MQ', credential_ids: ['Y3JlZC0y'] };
    const signalAllAcceptedCredentials = vi.fn(async () => undefined);
    vi.stubGlobal('PublicKeyCredential', Object.assign(function PublicKeyCredential() {}, { signalAllAcceptedCredentials }));
    stubFetch({ ...ROUTES, 'DELETE /api/auth/passkeys/4': () => reply({ accepted }) });
    wrap(<SignInDevices />);
    fireEvent.click(await screen.findByRole('button', { name: 'Remove iPhone' }));
    expect(signalAllAcceptedCredentials).not.toHaveBeenCalled();
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Remove' }));
    await waitFor(() => expect(signalAllAcceptedCredentials).toHaveBeenCalledWith(
      { rpId: 'nas.example.ts.net', userId: 'MQ', allAcceptedCredentialIds: ['Y3JlZC0y'] }));
  });
  it('signing out another device asks first and says the other devices stay', async () => {
    const fetchMock = stubFetch({ ...ROUTES, 'DELETE /api/auth/sessions/11': () => new Response(null, { status: 204 }) });
    wrap(<SignInDevices />);
    fireEvent.click(await screen.findByRole('button', { name: 'Sign out, iPhone' }));
    const ask = screen.getByRole('dialog', { name: 'Sign out iPhone?' });
    expect(within(ask).getByText('That device is signed out now and needs your password or a passkey to get back in. This device and your other devices stay signed in.')).toBeInTheDocument();
    expect(callsTo(fetchMock, 'DELETE', '/api/auth/sessions')).toHaveLength(0);
    fireEvent.click(within(ask).getByRole('button', { name: 'Sign out' }));
    await waitFor(() => expect(callsTo(fetchMock, 'DELETE', '/api/auth/sessions/11')).toHaveLength(1));
  });
  it('after removing a passkey, says which and keeps focus on the list (THO-1)', async () => {
    let passkeys = PASSKEYS;
    stubFetch({ ...ROUTES, '/api/auth/passkeys': () => reply(passkeys),
      'DELETE /api/auth/passkeys/4': () => { passkeys = { passkeys: [] }; return new Response(null, { status: 204 }); } });
    wrap(<SignInDevices />);
    const button = await screen.findByRole('button', { name: 'Remove iPhone' });
    button.focus();
    fireEvent.click(button);
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Remove' }));
    await expectRemovalSaid('Removed the passkey iPhone.', () => screen.getByRole('heading', { name: 'Passkeys' }));
  });
  it('after signing out another device, says which and keeps focus on the list (THO-1)', async () => {
    let sessions = SESSIONS;
    stubFetch({ ...ROUTES, '/api/auth/sessions': () => reply(sessions),
      'DELETE /api/auth/sessions/11': () => { sessions = { sessions: [SESSIONS.sessions[0]] }; return new Response(null, { status: 204 }); } });
    wrap(<SignInDevices />);
    const button = await screen.findByRole('button', { name: 'Sign out, iPhone' });
    button.focus();
    fireEvent.click(button);
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Sign out' }));
    await expectRemovalSaid('Signed out iPhone.', () => screen.getByRole('heading', { name: 'Signed-in devices' }));
  });
  it('signing out this device asks first and says the other devices stay signed in', async () => {
    const fetchMock = stubFetch({ ...ROUTES, 'POST /api/auth/logout': () => new Response(null, { status: 204 }) });
    wrap(<SignInDevices />);
    fireEvent.click(await screen.findByRole('button', { name: 'Sign out, JR’s laptop' }));
    const ask = screen.getByRole('dialog', { name: 'Sign out of this device?' });
    expect(within(ask).getByText("You'll need your password or a passkey to sign in here again. Your other devices stay signed in.")).toBeInTheDocument();
    expect(callsTo(fetchMock, 'POST', '/api/auth/logout')).toHaveLength(0);
    fireEvent.click(within(ask).getByRole('button', { name: 'Sign out' }));
    await waitFor(() => expect(callsTo(fetchMock, 'POST', '/api/auth/logout')).toHaveLength(1));
  });
  it('a changed password says passkeys still sign in, so one someone else added gets removed', async () => {
    stubFetch({ ...ROUTES, 'POST /api/auth/password': {} });
    wrap(<SignInDevices />);
    fireEvent.change(await screen.findByLabelText('Current password'), { target: { value: 'old-pass-word-1' } });
    fireEvent.change(screen.getByLabelText('New password'), { target: { value: 'new-pass-word-2' } });
    fireEvent.click(screen.getByRole('button', { name: 'Change my password' }));
    expect(await screen.findByText("Your password is changed. Other devices were signed out. Passkeys still sign in, so remove any you don't recognize.")).toBeInTheDocument();
  });
  it('is a page of its own with the sign-in controls', async () => {
    stubFetch(ROUTES);
    wrap(<SignInDevices />);
    expect(screen.getByRole('heading', { level: 1, name: 'Sign-in and devices' })).toBeInTheDocument();
    expect(await screen.findByRole('button', { name: 'Change my password' })).toBeInTheDocument();
  });
});
