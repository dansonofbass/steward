import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { CHANGE_PASSWORD, FORGOT, NEW_PASSWORD, PASSWORD_CHANGED, RESET_LINK_GONE, RESET_NO_LINK } from '../lib/copy';
import { callsTo, reply, stubFetch } from '../test-utils';
import Reset from './Reset';

afterEach(() => vi.unstubAllGlobals());

function open(path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/reset" element={<Reset />} />
          <Route path="/forgot" element={<p>forgot page</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('the reset page (#19)', () => {
  it('with no token it shows the no-link state, not the form, and links to Forgot your password', () => {
    const f = stubFetch({});
    open('/reset');
    expect(screen.getByText(RESET_NO_LINK)).toBeInTheDocument();
    expect(screen.queryByLabelText(NEW_PASSWORD)).toBeNull();
    expect(screen.queryByRole('button', { name: CHANGE_PASSWORD })).toBeNull();
    fireEvent.click(screen.getByRole('link', { name: FORGOT }));
    expect(screen.getByText('forgot page')).toBeInTheDocument();
    expect(f).not.toHaveBeenCalled();
  });

  it('an invite link with no token gets the same no-link state', () => {
    stubFetch({});
    open('/reset?invite=1');
    expect(screen.getByText(RESET_NO_LINK)).toBeInTheDocument();
    expect(screen.queryByLabelText(NEW_PASSWORD)).toBeNull();
  });

  it('an expired link says so, drops the form, and links to Forgot your password', async () => {
    const f = stubFetch({ 'POST /api/auth/reset': () => reply({ error: RESET_LINK_GONE, gone: true }, 400) });
    open('/reset?token=old');
    fireEvent.change(screen.getByLabelText(NEW_PASSWORD), { target: { value: 'a-long-new-password-1' } });
    fireEvent.click(screen.getByRole('button', { name: CHANGE_PASSWORD }));
    expect(await screen.findByText(RESET_LINK_GONE)).toBeInTheDocument();
    expect(screen.queryByLabelText(NEW_PASSWORD)).toBeNull();
    expect(screen.getByRole('link', { name: FORGOT }).getAttribute('href')).toBe('/forgot');
    expect(callsTo(f, 'POST', '/api/auth/reset')[0].body).toEqual({ token: 'old', password: 'a-long-new-password-1' });
  });

  it('a weak password keeps the form and its words', async () => {
    stubFetch({ 'POST /api/auth/reset': () => reply({ error: 'Use at least 12 characters.' }, 400) });
    open('/reset?token=good');
    fireEvent.change(screen.getByLabelText(NEW_PASSWORD), { target: { value: 'short' } });
    fireEvent.click(screen.getByRole('button', { name: CHANGE_PASSWORD }));
    expect(await screen.findByText('Use at least 12 characters.')).toBeInTheDocument();
    expect(screen.getByLabelText(NEW_PASSWORD)).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: FORGOT })).toBeNull();
  });

  it('a good link changes the password', async () => {
    stubFetch({ 'POST /api/auth/reset': { user: { id: 1 } } });
    open('/reset?token=good');
    fireEvent.change(screen.getByLabelText(NEW_PASSWORD), { target: { value: 'a-long-new-password-1' } });
    fireEvent.click(screen.getByRole('button', { name: CHANGE_PASSWORD }));
    expect(await screen.findByText(PASSWORD_CHANGED)).toBeInTheDocument();
  });
});
