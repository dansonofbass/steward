import { fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ME, callsTo, reply, renderAt, stubFetch, type Route } from '../../test-utils';
import type { WelcomeState } from './api';
import Welcome from './Welcome';

const fx = vi.hoisted(() => ({ acorn: vi.fn((_o: { motion: string }) => () => {}), winMoment: vi.fn(() => () => {}) }));
vi.mock('../../celebrate/celebrate', () => fx);

const STATE: WelcomeState = { kind: 'partner', seen: false, inviter: 'Pat', money: { in: true, linked: false, accounts: 1, rows: 9 },
  waiting: 0, zone_needed: false, step: 'money' };
const routes = (state: Partial<WelcomeState> = {}, extra: Record<string, Route> = {}): Record<string, Route> => ({
  '/api/welcome': () => reply({ ...STATE, ...state }), '/api/auth/me': ME, 'POST /api/books/ours/welcome': { ok: true },
  'POST /api/books/mom/welcome': { ok: true }, 'PATCH /api/auth/me': { ok: true }, ...extra,
});
const mount = (book = {}, path = '/welcome') => renderAt(<Welcome />, book, path);
const next = async () => fireEvent.click(await screen.findByRole('button', { name: 'Next' }));
const acorns = (c: HTMLElement) => c.querySelectorAll('svg.acorn').length;

beforeEach(() => { vi.clearAllMocks(); localStorage.clear(); });
afterEach(() => vi.unstubAllGlobals());

describe('the partner welcome', () => {
  it('household manager: the acorn, still, and the manager line', async () => {
    stubFetch(routes());
    const { container } = mount();
    expect(await screen.findByRole('heading', { name: 'Welcome to Ours' })).toBeInTheDocument();
    expect(screen.getByText("Pat keeps your household's money here, on your own server.")).toBeInTheDocument();
    expect(screen.getByText('You can see everything and change it.')).toBeInTheDocument();
    expect(acorns(container)).toBe(1);
    expect(fx.acorn).not.toHaveBeenCalled();
  });

  it('household viewer: the viewer line', async () => {
    stubFetch(routes());
    mount({ role: 'viewer' });
    expect(await screen.findByText('You can see everything. Changes are for managers.')).toBeInTheDocument();
  });

  it("parent book: no acorn, the book's name", async () => {
    stubFetch(routes());
    const { container } = mount({ kind: 'parent', name: 'Mom' });
    expect(await screen.findByText("Pat keeps Mom's money here, on your own server.")).toBeInTheDocument();
    expect(screen.getByText('You can see everything and change it.')).toBeInTheDocument();
    expect(acorns(container)).toBe(0);
  });

  it('with no inviter, the line starts Your household', async () => {
    stubFetch(routes({ inviter: null }));
    mount();
    expect(await screen.findByText("Your household keeps its money here, on your own server.")).toBeInTheDocument();
  });

  it("screen 2 saves the person's own switches with PATCH /api/auth/me", async () => {
    const calls = stubFetch(routes());
    mount();
    await next();
    expect(await screen.findByRole('heading', { name: 'Your switches' })).toBeInTheDocument();
    expect(screen.getByText('Yours alone.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('switch', { name: 'Celebrations' }));
    await waitFor(() => expect(callsTo(calls, 'PATCH', '/api/auth/me')).toHaveLength(1));
    expect(callsTo(calls, 'PATCH', '/api/auth/me')[0]!.body).toEqual({ celebrations: false });
  });

  it("screen 3 shows the manager's Review line with its icon, or the viewer's line", async () => {
    stubFetch(routes());
    const m = mount();
    await next(); await next();
    expect(await screen.findByRole('heading', { name: 'Your name on your work' })).toBeInTheDocument();
    expect(m.container.textContent).toContain('New spending waits in  Review for a category.');
    expect(m.container.querySelector('.welcome__nav svg')).not.toBeNull();
    expect(screen.getByRole('button', { name: 'Go to Home' })).toBeInTheDocument();
    m.unmount();
    stubFetch(routes());
    mount({ role: 'viewer' });
    await next(); await next();
    expect(await screen.findByText('Every change shows who made it. Most can be undone for 15 minutes.')).toBeInTheDocument();
    expect(screen.queryByText(/Review/)).toBeNull();
  });

  it('Skip on any screen and Go to Home mark it and go Home; a replay marks nothing', async () => {
    const calls = stubFetch(routes());
    const m = mount();
    fireEvent.click(await screen.findByRole('button', { name: 'Skip' }));
    await waitFor(() => expect(m.location.current.pathname).toBe('/b/ours'));
    expect(callsTo(calls, 'POST', '/api/books/ours/welcome')).toHaveLength(1);
    m.unmount();

    const again = stubFetch(routes());
    const r = mount({}, '/welcome?again=1');
    await next(); await next();
    fireEvent.click(await screen.findByRole('button', { name: 'Go to Home' }));
    await waitFor(() => expect(r.location.current.pathname).toBe('/b/ours'));
    expect(callsTo(again, 'POST', '/api/books/ours/welcome')).toHaveLength(0);
  });

  it('never links to Get Steward ready', async () => {
    stubFetch(routes());
    mount();
    for (let i = 0; i < 3; i++) {
      await screen.findByRole('button', { name: i < 2 ? 'Next' : 'Go to Home' });
      expect(screen.queryByRole('link', { name: /Get Steward ready/ })).toBeNull();
      if (i < 2) await next();
    }
  });
});
