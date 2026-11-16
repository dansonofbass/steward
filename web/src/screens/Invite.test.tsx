import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { callsTo, reply, stubFetch } from '../test-utils';
import Invite from './Invite';

afterEach(() => vi.unstubAllGlobals());

function Landed() {
  const loc = useLocation();
  return <p>{`landed ${loc.pathname} ${JSON.stringify(loc.state)}`}</p>;
}
function open(path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/invite" element={<Invite />} />
          <Route path="/b/:slug" element={<Landed />} />
          <Route path="/" element={<p>home page</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
const ME = { user: { id: 1, username: 'vee', display_name: 'Vee' }, books: [], session: { id: 1, device_label: 'x', created_at: '2026-10-01T00:00:00Z' } };

describe('the invite page', () => {
  it('accepts once, refreshes the books, then opens the book with the joined line', async () => {
    const order: string[] = [];
    const fetchMock = stubFetch({
      'POST /api/invites/accept': () => { order.push('accept'); return reply({ book: { slug: 'mom', name: "Mom (Robin's)" } }); },
      '/api/auth/me': () => { order.push('me'); return reply(ME); },
    });
    open('/invite?token=abc');
    const landed = await screen.findByText(/landed \/b\/mom/);
    expect(landed.textContent).toContain('"joined":"Mom (Robin\'s)"');
    const accepts = callsTo(fetchMock, 'POST', '/api/invites/accept');
    expect(accepts).toHaveLength(1);
    expect(accepts[0].body).toEqual({ token: 'abc' });
    expect(order).toEqual(['accept', 'me']);
  });
  it("shows the server's words and a link to Home when the invite is gone", async () => {
    stubFetch({ 'POST /api/invites/accept': () => reply({ error: "That invite isn't here." }, 404) });
    open('/invite?token=old');
    expect(await screen.findByText("That invite isn't here.")).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Home' })).toHaveAttribute('href', '/');
  });
  it('without a token it offers Home and does not call the server', async () => {
    const fetchMock = stubFetch({});
    open('/invite');
    expect(await screen.findByRole('link', { name: 'Home' })).toBeInTheDocument();
    await waitFor(() => expect(callsTo(fetchMock, 'POST', '/api/invites/accept')).toHaveLength(0));
  });
  it('says the person joined when only the books refresh fails', async () => {
    stubFetch({
      'POST /api/invites/accept': () => reply({ book: { slug: 'mom', name: "Mom (Robin's)" } }),
      '/api/auth/me': () => reply({ error: 'Down for a moment.' }, 500),
    });
    open('/invite?token=abc');
    expect(await screen.findByText(/You joined Mom \(Robin's\)/)).toBeInTheDocument();
    expect(screen.queryByText(/landed/)).not.toBeInTheDocument();
    expect(screen.getByText(/You joined Mom/).closest('.notice')).toHaveClass('notice--warn');
    expect(screen.queryByRole('alert')).toBeNull();
    expect(screen.getByRole('link', { name: 'Home' })).toHaveAttribute('href', '/');
  });
});
