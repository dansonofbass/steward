import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import { Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../api/client';
import { reply, stubFetch, wrap } from '../test-utils';

vi.mock('../auth/passkeys', async (orig) => ({
  ...(await orig<typeof import('../auth/passkeys')>()),
  supported: () => true,
  offerPasskeysInAutofill: vi.fn(async () => null),
  signInWithPasskey: vi.fn(),
}));

import { offerPasskeysInAutofill, signInWithPasskey } from '../auth/passkeys';
import Login from './Login';

// Issue #7: a lock answers exactly as a wrong password does, so the server never says "locked". The page says what
// five wrong tries do instead, and the form stays usable: another username, or a passkey, still works.
const WRONG = "That username or password isn't right.";
const PAUSED = /Five wrong tries pause password sign-in for 15 minutes\. A passkey still works\./;

afterEach(() => vi.unstubAllGlobals());

async function miss(times: number) {
  for (let i = 0; i < times; i++) {
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByText(WRONG)).toBeInTheDocument();
    await vi.waitFor(() => expect(screen.getByRole('button', { name: 'Sign in' })).toBeEnabled());
  }
}

describe('five wrong passwords on the sign-in page', () => {
  it('say what happens next, and leave the form usable', async () => {
    stubFetch({ 'POST /api/auth/login': () => reply({ error: WRONG }, 401) });
    wrap(<Login />, '/login');
    fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'jr' } });
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'wrong-password-1' } });
    await miss(4);
    expect(screen.queryByText(PAUSED)).not.toBeInTheDocument();
    await miss(1);
    expect(screen.getByText(PAUSED)).toBeInTheDocument();
    expect(screen.getByLabelText('Password')).toBeEnabled();
    fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'sam' } });
    expect(screen.queryByText(PAUSED)).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Username'), { target: { value: ' JR' } });   // the same name, retyped
    expect(screen.getByText(PAUSED)).toBeInTheDocument();
  });

  it('count again from one for another name', async () => {
    stubFetch({ 'POST /api/auth/login': () => reply({ error: WRONG }, 401) });
    wrap(<Login />, '/login');
    fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'jr' } });
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'wrong-password-1' } });
    await miss(4);
    fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'sam' } });
    await miss(1);
    fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'jr' } });
    await miss(1);
    expect(screen.queryByText(PAUSED)).not.toBeInTheDocument();
  });
});

// Issue #13: the username box offers this site's passkeys in its autofill, and the button stops that wait first.
describe('passkeys from the username box', () => {
  const USER = { id: 1, username: 'jr', display_name: 'JR', email: null };
  const page = () => wrap(<Routes><Route path="/login" element={<Login />} /><Route path="/" element={<p>Home</p>} /></Routes>, '/login');
  const stopOf = (call = 0) => vi.mocked(offerPasskeysInAutofill).mock.calls[call][1];
  const hooksOf = (call = 0) => vi.mocked(offerPasskeysInAutofill).mock.calls[call][2];
  const typePassword = () => {
    fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'jr' } });
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'a-password-1' } });
  };

  beforeEach(() => {
    vi.mocked(offerPasskeysInAutofill).mockReset().mockResolvedValue(null);
    vi.mocked(signInWithPasskey).mockReset();
  });

  it('asks the browser for passkeys as well as saved names, and wants a name typed plainly', () => {
    page();
    const box = screen.getByLabelText('Username');
    expect(box).toHaveAttribute('autocomplete', 'username webauthn');
    expect(box).toBeRequired();
    expect(box).toHaveAttribute('spellcheck', 'false');
    expect(offerPasskeysInAutofill).toHaveBeenCalledTimes(1);
  });

  it('signs in with a passkey picked there', async () => {
    vi.mocked(offerPasskeysInAutofill).mockResolvedValueOnce(USER);
    page();
    expect(await screen.findByText('Home')).toBeInTheDocument();
  });

  it('says why a picked passkey was refused, under the passkey button', async () => {
    const unknown = "That passkey isn't registered any more. Sign in with your password and add it again.";
    vi.mocked(offerPasskeysInAutofill).mockImplementationOnce(async (_device, _stop, { onRefused }) => {
      onRefused(new ApiError(401, unknown));
      return null;
    });
    page();
    expect(await screen.findByText(unknown)).toBeInTheDocument();
  });

  it('offers passkeys there again after the button\'s prompt ends without signing in', async () => {
    vi.mocked(signInWithPasskey).mockRejectedValueOnce(new ApiError(0, 'The passkey prompt was closed or timed out. Try again.'));
    page();
    fireEvent.click(screen.getByRole('button', { name: 'Sign in with a passkey' }));
    expect(await screen.findByText('The passkey prompt was closed or timed out. Try again.')).toBeInTheDocument();
    expect(offerPasskeysInAutofill).toHaveBeenCalledTimes(2);
    expect(stopOf(0).aborted).toBe(true);
    expect(stopOf(1).aborted).toBe(false);
  });

  it('keeps the last start across restarts, so a restart waits out the minimum gap', async () => {
    vi.mocked(signInWithPasskey).mockRejectedValueOnce(new ApiError(0, 'The passkey prompt was closed or timed out. Try again.'));
    page();
    fireEvent.click(screen.getByRole('button', { name: 'Sign in with a passkey' }));
    await waitFor(() => expect(offerPasskeysInAutofill).toHaveBeenCalledTimes(2));
    expect(hooksOf(0).lastStart).toBeDefined();
    expect(hooksOf(1).lastStart).toBe(hooksOf(0).lastStart);
  });

  it('lets neither button start a sign-in while a passkey picked there is with the server', async () => {
    const login = vi.fn(() => reply({ user: USER }));
    stubFetch({ 'POST /api/auth/login': login });
    page();
    act(() => hooksOf().checking?.(true));
    const passkey = screen.getByRole('button', { name: 'Sign in with a passkey' });
    expect(passkey).toHaveAttribute('aria-busy', 'true');
    expect(screen.getByRole('button', { name: 'Sign in' })).toBeDisabled();
    typePassword();
    fireEvent.click(passkey);
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    fireEvent.submit(screen.getByLabelText('Password').closest('form')!);
    expect(signInWithPasskey).not.toHaveBeenCalled();
    expect(login).not.toHaveBeenCalled();
    expect(stopOf().aborted).toBe(false);
    act(() => hooksOf().checking?.(false));                   // refused: the page is usable again
    expect(screen.getByRole('button', { name: 'Sign in' })).toBeEnabled();
    expect(passkey).not.toHaveAttribute('aria-busy');
  });

  it('signs in with a pick the server accepted even if the wait was stopped while it was checked', async () => {
    let answer!: (user: typeof USER) => void;
    vi.mocked(offerPasskeysInAutofill).mockImplementationOnce(() => new Promise((r) => { answer = r; }));
    vi.mocked(signInWithPasskey).mockImplementationOnce(() => new Promise(() => {}));
    page();
    fireEvent.click(screen.getByRole('button', { name: 'Sign in with a passkey' }));   // pressed as the pick went in
    expect(stopOf().aborted).toBe(true);
    answer(USER);
    expect(await screen.findByText('Home')).toBeInTheDocument();
  });

  it('stops waiting there before a password try, and offers passkeys again when it fails', async () => {
    let stoppedFirst: boolean | undefined;
    stubFetch({ 'POST /api/auth/login': () => { stoppedFirst = stopOf().aborted; return reply({ error: WRONG }, 401); } });
    page();
    typePassword();
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByText(WRONG)).toBeInTheDocument();
    expect(stoppedFirst).toBe(true);
    expect(offerPasskeysInAutofill).toHaveBeenCalledTimes(2);
    expect(stopOf(1).aborted).toBe(false);
    expect(hooksOf(1).lastStart).toBe(hooksOf(0).lastStart);
  });

  it('stops waiting there before the button opens its own prompt', async () => {
    let stoppedFirst: boolean | undefined;
    vi.mocked(signInWithPasskey).mockImplementationOnce(async () => { stoppedFirst = stopOf().aborted; return USER; });
    page();
    expect(stopOf().aborted).toBe(false);
    fireEvent.click(screen.getByRole('button', { name: 'Sign in with a passkey' }));
    expect(await screen.findByText('Home')).toBeInTheDocument();
    expect(stoppedFirst).toBe(true);
  });

  it('stops waiting when the page closes', () => {
    const { unmount } = page();
    unmount();
    expect(stopOf().aborted).toBe(true);
  });

  it('keeps quiet when the wait ends without a pick', async () => {
    page();
    await waitFor(() => expect(offerPasskeysInAutofill).toHaveBeenCalled());
    expect(screen.queryByText("That didn't finish. Try again.")).toBeNull();
  });
});
