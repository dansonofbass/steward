import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { setCurrentBook } from '../../api/book';
import { callsTo, reply, stubFetch } from '../../test-utils';
import Setup from './Setup';
import * as C from './copy';

const passkeys = vi.hoisted(() => ({ supported: vi.fn(() => false), registerThisDevice: vi.fn(async () => ({})) }));
vi.mock('../../auth/passkeys', () => passkeys);

beforeEach(() => setCurrentBook(null));          // no book is open before anyone exists: /api/setup must be top-level
afterEach(() => { vi.unstubAllGlobals(); setCurrentBook('ours'); passkeys.supported.mockReturnValue(false); passkeys.registerThisDevice.mockClear(); });

const TOKEN = 'A'.repeat(43);
function Where() { const l = useLocation(); return <p data-testid="where">{`${l.pathname}${l.hash}`}</p>; }
function open(path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/setup" element={<><Setup /><Where /></>} />
          <Route path="/" element={<p>home page</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
function fill() {
  fireEvent.change(screen.getByLabelText(C.YOUR_NAME), { target: { value: 'Casey' } });
  fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'casey' } });
  fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'casey@example.com' } });
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'pw-first-person-1' } });
}

describe('the first-run page (release spec, section 6)', () => {
  it('reads the token from the fragment once, then takes it out of the address', async () => {
    const f = stubFetch({ 'POST /api/setup/check': { ok: true } });
    open(`/setup#${TOKEN}`);
    expect(await screen.findByLabelText(C.YOUR_NAME)).toBeInTheDocument();
    expect(screen.getByTestId('where').textContent).toBe('/setup');
    const [call] = callsTo(f, 'POST', '/api/setup/check');
    expect(call.body).toEqual({ token: TOKEN });
    expect(call.url).toBe('/api/setup/check');
  });

  it('makes the account with the token in the body and lands on Home', async () => {
    const f = stubFetch({ 'POST /api/setup/check': { ok: true }, 'POST /api/setup': { user: { id: 1, username: 'casey', display_name: 'Casey' } } });
    open(`/setup#${TOKEN}`);
    await screen.findByLabelText(C.YOUR_NAME);
    fill();
    fireEvent.click(screen.getByRole('button', { name: C.MAKE_ACCOUNT }));
    expect(await screen.findByText('home page')).toBeInTheDocument();
    const [made] = callsTo(f, 'POST', '/api/setup').filter((c) => c.url === '/api/setup');
    expect(made.body).toMatchObject({ token: TOKEN, display_name: 'Casey', username: 'casey', email: 'casey@example.com', password: 'pw-first-person-1' });
  });

  it('offers a passkey when the device can, with the password just chosen, and Not now still lands on Home', async () => {
    passkeys.supported.mockReturnValue(true);
    stubFetch({ 'POST /api/setup/check': { ok: true }, 'POST /api/setup': { user: { id: 1, username: 'casey', display_name: 'Casey' } } });
    open(`/setup#${TOKEN}`);
    await screen.findByLabelText(C.YOUR_NAME);
    fill();
    fireEvent.click(screen.getByRole('button', { name: C.MAKE_ACCOUNT }));
    fireEvent.click(await screen.findByRole('button', { name: C.ADD_PASSKEY }));
    expect(await screen.findByText('home page')).toBeInTheDocument();
    expect(passkeys.registerThisDevice).toHaveBeenCalledWith(expect.any(String), 'pw-first-person-1');
  });

  it("shows the server's words when the link is gone, and asks for the link when there's none", async () => {
    stubFetch({ 'POST /api/setup/check': () => reply({ error: C.LINK_GONE }, 400) });
    open(`/setup#${TOKEN}`);
    expect(await screen.findByText(C.LINK_GONE)).toBeInTheDocument();
    expect(screen.queryByLabelText(C.YOUR_NAME)).toBeNull();
  });

  it('with no token in the address it asks for the link and sends nothing', () => {
    const f = stubFetch({});
    open('/setup');
    expect(screen.getByText(C.NO_LINK)).toBeInTheDocument();
    expect(f).not.toHaveBeenCalled();
  });
});
