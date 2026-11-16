import { fireEvent, screen } from '@testing-library/react';
import { Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { reply, stubFetch, wrap } from '../test-utils';

// jsdom has no WebAuthn; the real signInWithPasskey still runs, and the 429 comes before any prompt.
vi.mock('../auth/passkeys', async (orig) => ({ ...(await orig<typeof import('../auth/passkeys')>()), supported: () => true }));

import Forgot from './Forgot';
import Invite from './Invite';
import Login from './Login';

// Hardening plan, Engineering choice 13: the server's own words for a 429, shown where the person tried.
const TOO_MANY = 'Too many tries. Try again in 15 minutes.';
const tooMany = () => reply({ error: TOO_MANY }, 429);

afterEach(() => vi.unstubAllGlobals());

describe("the server's too-many-tries answer reads plainly", () => {
  it('on Forgot your password', async () => {
    stubFetch({ 'POST /api/auth/forgot': tooMany });
    wrap(<Forgot />, '/forgot');
    fireEvent.change(screen.getByLabelText('Username or email'), { target: { value: 'jr' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send me a link' }));
    expect(await screen.findByText(TOO_MANY)).toBeInTheDocument();
  });

  it('on Sign in with a passkey, and the button works again', async () => {
    stubFetch({ 'POST /api/auth/passkeys/login/options': tooMany });
    wrap(<Login />, '/login');
    fireEvent.click(screen.getByRole('button', { name: 'Sign in with a passkey' }));
    expect(await screen.findByText(TOO_MANY)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Sign in with a passkey' })).toBeEnabled();
  });

  it('on an invitation link', async () => {
    stubFetch({ 'POST /api/invites/accept': tooMany });
    wrap(<Routes><Route path="/invite" element={<Invite />} /></Routes>, '/invite?token=abc');
    expect(await screen.findByText(TOO_MANY)).toBeInTheDocument();
  });
});
