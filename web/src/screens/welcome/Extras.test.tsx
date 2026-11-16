import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { POOLS } from '../../lib/lines';
import { ME, callsTo, reply, renderAt, stubFetch, type Route } from '../../test-utils';
import type { InstallSettings, Ready, ReadyRow } from '../ready/api';
import { MAIL_OFF_INVITE } from '../settings/inviteCopy';
import { forgetStepMoments } from './FirstRun';
import type { WelcomeState } from './api';
import Welcome from './Welcome';

const fx = vi.hoisted(() => ({ acorn: vi.fn((_o: { motion: string }) => () => {}), winMoment: vi.fn(() => () => {}) }));
vi.mock('../../celebrate/celebrate', () => fx);

const STATE: WelcomeState = { kind: 'first_run', seen: false, inviter: null, money: { in: true, linked: false, accounts: 1, rows: 9 },
  waiting: 0, zone_needed: false, step: 'extras' };
const row = (key: ReadyRow['key'], status: ReadyRow['status'], detail = '', extra = {}, lines: ReadyRow['lines'] = []): ReadyRow =>
  ({ key, status, detail, go: null, lines, extra });
const GATEWAY_LINE = { name: 'STEWARD_GATEWAY_URL', line: 'STEWARD_GATEWAY_URL=http://gw.example:8421', running: null, note: null, where: 'steward' as const };
const ready = (email: ReadyRow['status'] = 'optional', need = 0): Ready => ({ need, rows: [
  row('household', 'done'), row('money', 'done'), row('ask', 'optional', 'Not set up.', { url_set: false }, [GATEWAY_LINE]),
  row('email', email, 'Not set up.'), row('backups', 'done', 'First copy at 3:00 AM'), row('someone', 'optional'), row('address', 'done'), row('key', 'done')] });
const SETTINGS: InstallSettings = {
  email: { source: 'app', env: 'STEWARD_SMTP_*', host: '', port: 465, user: '', from: '', password_set: false, password_unreadable: false },
  backups: { at: { value: '03:00', source: 'default', env: 'STEWARD_BACKUP_AT' }, ping_url: { set: false, shown: null, source: 'app', env: 'X' }, dir: '/data/backups' },
  general: { timezone: { value: 'America/Chicago', source: 'env', env: 'Z', running: 'America/Chicago' }, gateway_name: { value: 'the gateway', source: 'default', env: 'G' } },
};
const MINE = { user_id: 1, username: 'jr', display_name: 'JR', email: 'jr@example.com', role: 'manager' };
let now: Ready;
let settings: InstallSettings;
let members: unknown[];
const routes = (extra: Record<string, Route> = {}): Record<string, Route> => ({
  '/api/welcome': () => reply(STATE), '/api/ready': () => reply(now), '/api/install/settings': () => reply(settings),
  '/api/books/ours/members': () => reply({ members }), '/api/auth/me': ME, 'POST /api/books/ours/welcome': { ok: true }, ...extra,
});
const mount = (path = '/welcome?step=extras') => renderAt(<Welcome />, {}, path);

beforeEach(() => { vi.clearAllMocks(); forgetStepMoments(); localStorage.clear(); now = ready(); settings = SETTINGS; members = [MINE]; });
afterEach(() => vi.unstubAllGlobals());

describe('the first run, A few extras', () => {
  it('lists four rows with their live status and the lede', async () => {
    stubFetch(routes());
    mount();
    expect(await screen.findByText('All optional. Get Steward ready keeps them for later.')).toBeInTheDocument();
    const rows = await screen.findAllByTestId('extras-row');
    expect(rows.map((r) => r.querySelector('.setup__title')!.textContent)).toEqual(['Your partner', 'Ask', 'Email', 'Backups']);
    expect(rows.map((r) => r.querySelector('.setup__status')!.textContent)).toEqual(['Optional', 'Optional', 'Optional', 'Done']);
    expect(within(rows[3]).getByText('A copy each night at 3:00 AM.')).toBeInTheDocument();
  });

  it('says what the ready row says when backups are off, never a sentence with no time', async () => {
    settings = { ...SETTINGS, backups: { ...SETTINGS.backups, at: { ...SETTINGS.backups.at, value: '' } } };
    now = { ...ready(), rows: ready().rows.map((r) => (r.key === 'backups' ? row('backups', 'optional', 'Off.') : r)) };
    stubFetch(routes());
    mount();
    const rows = await screen.findAllByTestId('extras-row');
    expect(within(rows[3]).getByText('Off.')).toBeInTheDocument();
    expect(screen.queryByText(/each night at \./)).toBeNull();
  });

  it('a partner already in the book, or invited, makes the row Done', async () => {
    members = [MINE, { status: 'Invited', invite_id: '7', email: 'pat@example.com', role: 'viewer', user_id: null, username: null, display_name: null }];
    stubFetch(routes());
    mount();
    const rows = await screen.findAllByTestId('extras-row');
    expect(rows[0].querySelector('.setup__status')!.textContent).toBe('Done');
  });

  it('opens the invite sheet, the Ask, Email and Backups panels in place', async () => {
    stubFetch(routes());
    mount();
    const rows = await screen.findAllByTestId('extras-row');
    fireEvent.click(rows[0]);
    expect(await screen.findByRole('dialog', { name: 'Invite someone' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Close/ }));
    fireEvent.click(rows[1]);
    expect(await screen.findByText('STEWARD_GATEWAY_URL=http://gw.example:8421')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Close/ }));
    fireEvent.click(rows[2]);
    expect(await screen.findByLabelText('Host')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Close/ }));
    fireEvent.click(rows[3]);
    expect(await screen.findByLabelText('Time')).toHaveValue('03:00');
  });

  it('shows the invite sheet line once it closes, the mail-off word included', async () => {
    stubFetch(routes({ 'POST /api/books/ours/members': () => reply({ member: { email: 'pat@example.com', role: 'viewer', status: 'Invited' }, invited: true, mail_off: true }, 201) }));
    mount();
    fireEvent.click((await screen.findAllByTestId('extras-row'))[0]);
    fireEvent.change(await screen.findByLabelText('Email'), { target: { value: 'pat@example.com' } });
    fireEvent.click(screen.getByRole('button', { name: 'Invite' }));
    expect(await screen.findByText(MAIL_OFF_INVITE)).toBeInTheDocument();
    fireEvent.click(screen.getAllByTestId('extras-row')[0]);
    await waitFor(() => expect(screen.queryByText(MAIL_OFF_INVITE)).toBeNull());
  });

  it('the help card has no acorn and no motion, and says the book is in once added', async () => {
    stubFetch(routes({ 'POST /api/books': () => reply({ book: { slug: 'mom', name: 'Mom', kind: 'parent', role: 'manager', available: true, reason: null, owners: [], profile: null } }, 201) }));
    const { location } = mount();
    await screen.findAllByTestId('extras-row');
    const card = screen.getByTestId('help-card');
    expect(within(card).queryByRole('img', { name: /acorn/i })).toBeNull();
    fireEvent.click(within(card).getByRole('button', { name: 'Add their book' }));
    const sheet = await screen.findByRole('dialog', { name: 'Add a book' });
    fireEvent.change(within(sheet).getByLabelText('Name'), { target: { value: 'Mom' } });
    fireEvent.click(within(sheet).getByRole('button', { name: 'Add book' }));
    expect(await within(screen.getByTestId('help-card')).findByText('Mom is in your books.')).toBeInTheDocument();
    expect(location.current.pathname).toBe('/b/ours/welcome');
    expect(within(screen.getByTestId('help-card')).queryByRole('img', { name: /acorn/i })).toBeNull();
  });

  it('an extra turning done hops and says a setupStep line', async () => {
    stubFetch(routes());
    const r = mount();
    await screen.findAllByTestId('extras-row');
    expect(fx.acorn).not.toHaveBeenCalled();
    now = ready('done');
    await act(async () => { await r.qc.invalidateQueries({ queryKey: ['ready'] }); });
    await waitFor(() => expect(fx.acorn).toHaveBeenCalledTimes(1));
    expect(fx.acorn).toHaveBeenCalledWith(expect.objectContaining({ motion: 'hop' }));
    expect(POOLS.setupStep).toContain(screen.getByTestId('step-line').textContent);
  });

  it('a row already done when the page opens never hops', async () => {
    now = ready('done');
    stubFetch(routes());
    mount();
    await screen.findAllByTestId('extras-row');
    expect(fx.acorn).not.toHaveBeenCalled();
    expect(screen.queryByTestId('step-line')).toBeNull();
  });

  it('coming back from Review with the sorts done plays one hop and a line', async () => {
    stubFetch(routes());
    renderAt(<Welcome />, {}, { pathname: '/welcome', state: { setupDone: 'sort' } });
    // the address has no step: the state's step is extras
    await screen.findAllByTestId('extras-row');
    await waitFor(() => expect(fx.acorn).toHaveBeenCalledTimes(1));
    expect(POOLS.setupStep).toContain(screen.getByTestId('step-line').textContent);
  });

  it('Finish marks the welcome and plants the acorn; Planted links to Get Steward ready only when a row needs them', async () => {
    now = ready('optional', 2);
    const f = stubFetch(routes());
    const first = mount();
    await screen.findAllByTestId('extras-row');
    fireEvent.click(screen.getByRole('button', { name: 'Finish' }));
    expect(await screen.findByRole('heading', { name: 'Planted.' })).toBeInTheDocument();
    expect(callsTo(f, 'POST', '/api/books/ours/welcome')).toHaveLength(1);
    expect(screen.getByText('It grows as your books do.')).toBeInTheDocument();
    expect(await screen.findByRole('link', { name: 'Get Steward ready · 2 to go' })).toHaveAttribute('href', '/b/ours/settings/ready');
    fireEvent.click(screen.getByRole('button', { name: 'Go to Home' }));
    await waitFor(() => expect(first.location.current.pathname).toBe('/b/ours'));
    first.unmount();
    now = ready('optional', 0);
    mount('/welcome?step=planted');
    await screen.findByRole('heading', { name: 'Planted.' });
    await waitFor(() => expect(callsTo(f, 'GET', '/api/ready').length).toBeGreaterThan(1));
    expect(screen.queryByRole('link', { name: /to go/ })).toBeNull();
  });

  it('a replay finishes without marking', async () => {
    const f = stubFetch(routes({ '/api/welcome': () => reply({ ...STATE, seen: true }) }));
    mount('/welcome?step=extras&again=1');
    await screen.findAllByTestId('extras-row');
    fireEvent.click(screen.getByRole('button', { name: 'Finish' }));
    expect(await screen.findByRole('heading', { name: 'Planted.' })).toBeInTheDocument();
    expect(callsTo(f, 'POST', '/api/books/ours/welcome')).toHaveLength(0);
  });
});
