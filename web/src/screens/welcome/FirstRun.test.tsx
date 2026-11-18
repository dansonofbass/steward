import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ME, callsTo, reply, renderAt, stubFetch, type Route } from '../../test-utils';
import { POOLS } from '../../lib/lines';
import { forgetStepMoments } from './FirstRun';
import type { WelcomeState } from './api';
import Welcome from './Welcome';

const fx = vi.hoisted(() => ({ acorn: vi.fn((_o: { motion: string }) => () => {}), winMoment: vi.fn(() => () => {}) }));
vi.mock('../../celebrate/celebrate', () => fx);

const state = (over: Partial<WelcomeState> = {}): WelcomeState => ({
  kind: 'first_run', seen: false, inviter: null, money: { in: false, linked: false, accounts: 0, rows: 0 }, waiting: 0, zone_needed: false,
  step: 'money', ...over,
});
let current: WelcomeState;
const routes = (extra: Record<string, Route> = {}): Record<string, Route> => ({
  '/api/welcome': () => reply(current), 'POST /api/books/ours/welcome': { ok: true }, '/api/auth/me': ME,
  'PUT /api/install/settings/general': { ok: true }, ...extra,
});
const mount = (path = '/welcome') => renderAt(<Welcome />, {}, path);
const zone = (tz: string | undefined) =>
  vi.spyOn(Intl.DateTimeFormat.prototype, 'resolvedOptions').mockReturnValue({ timeZone: tz } as Intl.ResolvedDateTimeFormatOptions);

beforeEach(() => { vi.clearAllMocks(); forgetStepMoments(); localStorage.clear(); current = state(); });
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe('the first run, Welcome', () => {
  it('opens on Welcome with the tagline, the privacy line and three ways on', async () => {
    stubFetch(routes());
    mount();
    expect(await screen.findByRole('heading', { name: 'Steward' })).toBeInTheDocument();
    expect(screen.getByText('Secure, private, thoughtful. For you, and the people you look after.')).toBeInTheDocument();
    expect(screen.getByText('Everything you enter stays on your home server.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Set up my household' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Look around with a sample household first' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Later' })).toBeInTheDocument();
  });

  it("shows the browser's time zone only when none is set, and saves it with either button", async () => {
    zone('America/Chicago');
    current = state({ zone_needed: true });
    const f = stubFetch(routes());
    mount();
    expect(await screen.findByText('Time zone: America/Chicago')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Set up my household' }));
    expect(await screen.findByRole('heading', { name: 'Bring in your money' })).toBeInTheDocument();
    expect(callsTo(f, 'PUT', '/api/install/settings/general').map((c) => c.body)).toEqual([{ timezone: 'America/Chicago' }]);
  });

  it('Change swaps the line for a list of zones, and the pick is what is saved', async () => {
    zone('America/Chicago');
    current = state({ zone_needed: true });
    const f = stubFetch(routes());
    mount();
    fireEvent.click(await screen.findByRole('button', { name: 'Change' }));
    fireEvent.change(screen.getByRole('combobox', { name: 'Time zone' }), { target: { value: 'Europe/Paris' } });
    fireEvent.click(screen.getByRole('button', { name: 'Set up my household' }));
    await screen.findByRole('heading', { name: 'Bring in your money' });
    expect(callsTo(f, 'PUT', '/api/install/settings/general')[0].body).toEqual({ timezone: 'Europe/Paris' });
  });

  it('shows no zone line and sends no PUT when one is set', async () => {
    zone('America/Chicago');
    const f = stubFetch(routes());
    mount();
    fireEvent.click(await screen.findByRole('button', { name: 'Set up my household' }));
    await screen.findByRole('heading', { name: 'Bring in your money' });
    expect(screen.queryByText(/Time zone:/)).toBeNull();
    expect(callsTo(f, 'PUT', '/api/install/settings/general')).toHaveLength(0);
  });

  it('a time zone the server refuses never blocks the first run', async () => {
    zone('America/Chicago');
    current = state({ zone_needed: true });
    stubFetch(routes({ 'PUT /api/install/settings/general': () => reply({ error: 'Not a zone.' }, 422) }));
    mount();
    fireEvent.click(await screen.findByRole('button', { name: 'Set up my household' }));
    expect(await screen.findByRole('heading', { name: 'Bring in your money' })).toBeInTheDocument();
    expect(screen.queryByText('Not a zone.')).toBeNull();
  });

  it('with no zone from the browser there is no line and no PUT', async () => {
    zone(undefined);
    current = state({ zone_needed: true });
    const f = stubFetch(routes());
    mount();
    fireEvent.click(await screen.findByRole('button', { name: 'Set up my household' }));
    await screen.findByRole('heading', { name: 'Bring in your money' });
    expect(screen.queryByText(/Time zone:/)).toBeNull();
    expect(callsTo(f, 'PUT', '/api/install/settings/general')).toHaveLength(0);
  });

  it('makes the Sample and opens it, saying so while it works', async () => {
    let made: (r: Response) => void = () => {};
    stubFetch(routes({ 'POST /api/books/sample': () => new Promise<Response>((res) => { made = res; }) }));
    const { location } = mount();
    fireEvent.click(await screen.findByRole('button', { name: 'Look around with a sample household first' }));
    const busy = await screen.findByRole('button', { name: 'Making the sample…' });
    expect(busy).toBeDisabled();
    await act(async () => { made(reply({ book: { slug: 'sample', name: 'Sample', kind: 'household', role: 'manager', available: true, reason: null, owners: [], profile: null, sample: true } }, 201)); });
    await waitFor(() => expect(location.current.pathname).toBe('/b/sample'));
  });

  it('Later marks the welcome and goes Home; a replay marks nothing', async () => {
    const f = stubFetch(routes());
    const first = mount();
    fireEvent.click(await screen.findByRole('link', { name: 'Later' }));
    await waitFor(() => expect(first.location.current.pathname).toBe('/b/ours'));
    expect(callsTo(f, 'POST', '/api/books/ours/welcome')).toHaveLength(1);
    first.unmount();
    current = state({ seen: true });
    const again = mount('/welcome?again=1');
    fireEvent.click(await screen.findByRole('link', { name: 'Later' }));
    await waitFor(() => expect(again.location.current.pathname).toBe('/b/ours'));
    expect(callsTo(f, 'POST', '/api/books/ours/welcome')).toHaveLength(1);
  });

  it('a replay opens on Welcome even where the first run would resume', async () => {
    current = state({ seen: true, step: 'sort', waiting: 12, money: { in: true, linked: false, accounts: 1, rows: 40 } });
    stubFetch(routes());
    mount('/welcome?again=1');
    expect(await screen.findByRole('heading', { name: 'Steward' })).toBeInTheDocument();
  });

  it('a seen welcome goes Home', async () => {
    current = state({ seen: true });
    stubFetch(routes());
    const { location } = mount();
    await waitFor(() => expect(location.current.pathname).toBe('/b/ours'));
  });

  it('no welcome for this person goes Home', async () => {
    current = state({ kind: null, seen: true });
    stubFetch(routes());
    const { location } = mount();
    await waitFor(() => expect(location.current.pathname).toBe('/b/ours'));
  });
});

describe('the first run, the steps', () => {
  it('resumes at the first step not done', async () => {
    current = state({ step: 'sort', waiting: 12, money: { in: true, linked: false, accounts: 1, rows: 40 } });
    stubFetch(routes());
    mount();
    expect(await screen.findByRole('heading', { name: 'Sort a few' })).toBeInTheDocument();
    expect(screen.getByText('12 wait in Review. Sort a few to get the feel.')).toBeInTheDocument();
    expect(screen.getByRole('img', { name: 'Step 2 of 3' })).toBeInTheDocument();
  });

  it('opens on Welcome when the money is not in, whatever the step says', async () => {
    stubFetch(routes());
    mount();
    expect(await screen.findByRole('heading', { name: 'Steward' })).toBeInTheDocument();
  });

  it("ticks the money card with the import's line or the link's", async () => {
    current = state({ step: 'sort', waiting: 12, money: { in: true, linked: false, rows: 143, accounts: 2 } });
    stubFetch(routes());
    const first = mount('/welcome?step=money');
    expect(await screen.findByText('143 rows in. 12 to sort in Review.')).toBeInTheDocument();
    first.unmount();
    current = state({ step: 'sort', money: { in: true, linked: true, rows: 0, accounts: 4 } });
    mount('/welcome?step=money');
    expect(await screen.findByText('Linked. 4 accounts.')).toBeInTheDocument();
  });

  it('hops once, with a line, when the money comes in during the visit', async () => {
    stubFetch(routes());
    const r = mount('/welcome?step=money');
    await screen.findByRole('heading', { name: 'Bring in your money' });
    expect(fx.acorn).not.toHaveBeenCalled();
    current = state({ step: 'sort', waiting: 3, money: { in: true, linked: false, rows: 9, accounts: 1 } });
    await act(async () => { await r.qc.invalidateQueries({ queryKey: ['welcome'] }); });
    await waitFor(() => expect(fx.acorn).toHaveBeenCalledTimes(1));
    expect(fx.acorn).toHaveBeenCalledWith(expect.objectContaining({ motion: 'hop' }));
    expect(POOLS.setupStep).toContain(screen.getByTestId('step-line').textContent);
    await act(async () => { await r.qc.invalidateQueries({ queryKey: ['welcome'] }); });
    expect(fx.acorn).toHaveBeenCalledTimes(1);
  });

  it('hops when the money is in on coming back from Import in the same page load, and not twice', async () => {
    stubFetch(routes());
    const away = mount('/welcome?step=money');
    await screen.findByRole('heading', { name: 'Bring in your money' });
    away.unmount();
    current = state({ step: 'sort', waiting: 3, money: { in: true, linked: false, rows: 9, accounts: 1 } });
    const back = mount('/welcome?step=money');
    await screen.findByText('9 rows in. 3 to sort in Review.');
    await waitFor(() => expect(fx.acorn).toHaveBeenCalledTimes(1));
    back.unmount();
    mount('/welcome?step=money');
    await screen.findByText('9 rows in. 3 to sort in Review.');
    expect(fx.acorn).toHaveBeenCalledTimes(1);
  });

  it('a step already done the first time it is seen never hops', async () => {
    current = state({ step: 'sort', money: { in: true, linked: false, rows: 9, accounts: 1 } });
    stubFetch(routes());
    mount('/welcome?step=money');
    await screen.findByText('9 rows in, and nothing to sort.');
    expect(fx.acorn).not.toHaveBeenCalled();
    expect(screen.queryByTestId('step-line')).toBeNull();
  });

  it('Import opens the wizard from welcome; Start sorting opens Review from welcome', async () => {
    stubFetch(routes());
    const first = mount('/welcome?step=money');
    expect(await screen.findByRole('link', { name: 'Import' })).toHaveAttribute('href', '/b/ours/settings/import?from=welcome');
    first.unmount();
    current = state({ step: 'sort', waiting: 5, money: { in: true, linked: false, accounts: 1, rows: 9 } });
    mount();
    expect(await screen.findByRole('link', { name: 'Start sorting' })).toHaveAttribute('href', '/b/ours/review?from=welcome');
  });

  it('Link your banks opens the token form inline', async () => {
    stubFetch(routes());
    mount('/welcome?step=money');
    fireEvent.click(await screen.findByRole('button', { name: 'Link' }));
    expect(screen.getByLabelText('Setup token')).toBeInTheDocument();
  });

  it('Next and Skip for now both go on, and Next goes from money to sort to extras', async () => {
    stubFetch(routes());
    const { location } = mount('/welcome?step=money');
    fireEvent.click(await screen.findByRole('button', { name: 'Skip for now' }));
    await screen.findByRole('heading', { name: 'Sort a few' });
    expect(location.current.search).toBe('?step=sort');
    expect(screen.getByText('Nothing to sort yet.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    await waitFor(() => expect(location.current.search).toBe('?step=extras'));
  });

  it('says Nothing to sort when the money is in and nothing waits', async () => {
    current = state({ step: 'sort', money: { in: true, linked: false, accounts: 1, rows: 9 } });
    stubFetch(routes());
    mount('/welcome?step=sort');
    expect(await screen.findByText('Nothing to sort.')).toBeInTheDocument();
  });

  it('the three middle screens say Step n of 3, and the first says nothing', async () => {
    stubFetch(routes());
    const first = mount('/welcome?step=hello');
    await screen.findByRole('heading', { name: 'Steward' });
    expect(screen.queryByRole('img', { name: /Step \d of 3/ })).toBeNull();
    first.unmount();
    const money = mount('/welcome?step=money');
    expect(await screen.findByRole('img', { name: 'Step 1 of 3' })).toBeInTheDocument();
    money.unmount();
    const sort = mount('/welcome?step=sort');
    expect(await screen.findByRole('img', { name: 'Step 2 of 3' })).toBeInTheDocument();
    sort.unmount();
    mount('/welcome?step=extras');
    expect(await screen.findByRole('img', { name: 'Step 3 of 3' })).toBeInTheDocument();
  });
});
