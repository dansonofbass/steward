import { screen, waitFor } from '@testing-library/react';
import { Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { callsTo, ME, reply, stubFetch, wrap } from '../test-utils';
import { RequireAuth } from './RequireAuth';

afterEach(() => vi.unstubAllGlobals());
const routes = (
  <Routes>
    <Route element={<RequireAuth />}><Route path="/b/ours" element={<p>Inside</p>} /></Route>
    <Route path="/login" element={<p>Sign in</p>} />
  </Routes>
);

describe('RequireAuth', () => {
  it('lets a signed-in person through', async () => {
    stubFetch({ '/api/auth/me': { user: { id: 1, username: 'jr', display_name: 'JR' }, session: { id: 1, device_label: '', created_at: '' }, books: [] } });
    wrap(routes, '/b/ours');
    expect(await screen.findByText('Inside')).toBeInTheDocument();
  });
  it('sends everyone else to sign in', async () => {
    stubFetch({ '/api/auth/me': () => reply({ error: 'Please sign in.' }, 401) });
    wrap(routes, '/b/ours');
    expect(await screen.findByText('Sign in')).toBeInTheDocument();
  });
  it("adopts this device's stored switch once the person is known (phase 17 spec 3.6)", async () => {
    localStorage.setItem('steward-sound', 'on');
    const fetchMock = stubFetch({
      '/api/auth/me': { ...ME, user: { ...ME.user, prefs: { celebrations: null, sound: null } } },
      'PATCH /api/auth/me': { user: { id: 1, username: 'jr', display_name: 'JR', prefs: { celebrations: null, sound: true } } },
    });
    wrap(routes, '/b/ours');
    await waitFor(() => expect(callsTo(fetchMock, 'PATCH', '/api/auth/me').map((c) => c.body)).toEqual([{ sound: true }]));
    expect(localStorage.getItem('steward-sound')).toBeNull();
  });
  it('takes the gateway name from /me before any screen renders (spec 2026-11-05, section 7)', async () => {
    const { gw } = await import('../lib/gatewayName');
    const Probe = () => <p>{gw('{gateway} is answering')}</p>;
    stubFetch({ '/api/auth/me': { ...ME, gateway_name: 'Zebra-Box' } });
    wrap(<Routes><Route element={<RequireAuth />}><Route path="/b/ours" element={<Probe />} /></Route></Routes>, '/b/ours');
    expect(await screen.findByText('Zebra-Box is answering')).toBeInTheDocument();
  });
});
