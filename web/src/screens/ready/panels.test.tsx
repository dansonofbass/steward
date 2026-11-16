import { fireEvent, screen, within } from '@testing-library/react';
import { useState } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { callsTo, expectRemovalSaid, reply, stubFetch, wrapBook } from '../../test-utils';
import type { InstallSettings, ReadyRow } from './api';
import { BackupsPanel } from './BackupsPanel';
import { EmailPanel } from './EmailPanel';
import { GatewayPanel } from './GatewayPanel';
import { StewardSettings } from './StewardSettings';

afterEach(() => vi.unstubAllGlobals());

const EMAIL: InstallSettings['email'] = { source: 'app', env: 'STEWARD_SMTP_*', host: '', port: 465, user: '', from: '', password_set: false, password_unreadable: false };
const BACKUPS: InstallSettings['backups'] = { at: { value: '03:00', source: 'default', env: 'STEWARD_BACKUP_AT' },
  ping_url: { set: true, shown: 'hc-ping.example/…9f2c', source: 'app', env: 'STEWARD_BACKUP_PING_URL' }, dir: '/data/backups' };
const GENERAL: InstallSettings['general'] = { timezone: { value: 'America/Los_Angeles', source: 'env', env: 'STEWARD_TIMEZONE', running: 'America/Los_Angeles' },
  gateway_name: { value: 'the gateway', source: 'default', env: 'STEWARD_GATEWAY_NAME' } };
const row = (key: ReadyRow['key'], extra = {}): ReadyRow => ({ key, status: 'optional', detail: '', go: null, lines: [], extra });
const type = (label: string, value: string) => fireEvent.change(screen.getByLabelText(label), { target: { value } });

describe('EmailPanel', () => {
  it('shows an email group the settings file owns as read-only, with the password as Set', () => {
    wrapBook(<EmailPanel s={{ ...EMAIL, source: 'env', host: 'smtp.example.com', user: 'steward', from: 'steward@example.com', password_set: true }} />);
    for (const label of ['Host', 'Port', 'User', 'Password', 'From']) expect(screen.getByLabelText(label)).toBeDisabled();
    expect(screen.getByText('Set in your settings file (STEWARD_SMTP_*)')).toBeInTheDocument();
    expect(screen.getByLabelText('Password')).toHaveValue('');
    expect(screen.getByText('Set')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Save' })).toBeNull();
  });

  it('saves without a password key when the password field is empty, and says Saved. in place', async () => {
    const f = stubFetch({ 'PUT /api/install/settings/email': () => reply(EMAIL) });
    wrapBook(<EmailPanel s={{ ...EMAIL, password_set: true }} />);
    type('Host', 'smtp.example.com'); type('User', 'steward'); type('From', 'steward@example.com');
    expect(screen.getByLabelText('Port')).toHaveAttribute('type', 'number');
    expect(screen.getByLabelText('Password')).toHaveAttribute('type', 'password');
    expect(screen.getByLabelText('Password')).toHaveAttribute('autocomplete', 'new-password');
    expect(screen.getByLabelText('Password')).toHaveAttribute('placeholder', 'Set');
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(await screen.findByText('Saved.')).toBeInTheDocument();
    expect(callsTo(f, 'PUT', '/api/install/settings/email')[0].body).toEqual({ host: 'smtp.example.com', port: 465, user: 'steward', from: 'steward@example.com' });
  });

  it('keeps Saved. in place when the refetch flips the source to app', async () => {
    stubFetch({ 'PUT /api/install/settings/email': () => reply(EMAIL) });
    function Parent() {
      const [source, setSource] = useState<'default' | 'app'>('default');
      return <><EmailPanel s={{ ...EMAIL, source }} /><button onClick={() => setSource('app')}>refetched</button></>;
    }
    wrapBook(<Parent />);
    type('Host', 'smtp.example.com');
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(await screen.findByText('Saved.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'refetched' }));
    expect(screen.getByText('Saved.')).toBeInTheDocument();
    expect(screen.getByLabelText('Host')).toHaveValue('smtp.example.com');
  });

  it('asks the password again when the saved one cannot be read', () => {
    wrapBook(<EmailPanel s={{ ...EMAIL, password_set: true, password_unreadable: true }} />);
    expect(screen.getByText('Enter the password again.')).toBeInTheDocument();
  });

  it('removes app-stored email only after the sheet confirms', async () => {
    const f = stubFetch({ 'DELETE /api/install/settings/email': () => reply(EMAIL) });
    wrapBook(<EmailPanel s={{ ...EMAIL, host: 'smtp.example.com' }} />);
    const button = screen.getByRole('button', { name: 'Remove the email settings' });
    button.focus();
    fireEvent.click(button);
    const sheet = screen.getByRole('dialog');
    expect(within(sheet).getByText('Remove the email settings?')).toBeInTheDocument();
    expect(within(sheet).getByText('Invites and resets stop sending.')).toBeInTheDocument();
    expect(callsTo(f, 'DELETE', '/api/install/settings/email')).toHaveLength(0);
    fireEvent.click(within(sheet).getByRole('button', { name: 'Remove' }));
    await vi.waitFor(() => expect(callsTo(f, 'DELETE', '/api/install/settings/email')).toHaveLength(1));
    // THO-1: the Remove can go with the app-stored settings, so the line says it and holds focus.
    await expectRemovalSaid('Removed the email settings.', () => screen.getByText('Removed the email settings.').closest('[aria-live]') as HTMLElement);
  });

  it('shows the answer to Send a test, or the refusal, and asks the checklist again', async () => {
    let n = 0;
    const f = stubFetch({ 'POST /api/install/email/test': () => (n++ === 0 ? reply({ line: 'Sent to pat@x.com. Check your inbox.' })
      : reply({ error: 'The server refused the user name or password.' }, 422)) });
    const { qc } = wrapBook(<EmailPanel s={{ ...EMAIL, host: 'smtp.example.com' }} />);
    const spy = vi.spyOn(qc, 'invalidateQueries');
    fireEvent.click(screen.getByRole('button', { name: 'Send a test' }));
    expect(await screen.findByText('Sent to pat@x.com. Check your inbox.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Send a test' }));
    expect(await screen.findByText('The server refused the user name or password.')).toBeInTheDocument();
    expect(callsTo(f, 'POST', '/api/install/email/test')).toHaveLength(2);
    expect(spy).toHaveBeenCalledWith({ queryKey: ['ready'] });
  });
});

describe('BackupsPanel', () => {
  it('Off sends at: null, and a time the settings file owns is read-only', async () => {
    const f = stubFetch({ 'PUT /api/install/settings/backups': () => reply({}) });
    const { unmount } = wrapBook(<BackupsPanel s={BACKUPS} row={row('backups')} />);
    expect(screen.getByText('Copies go to /data/backups.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('switch', { name: 'Off' }));
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await vi.waitFor(() => expect(callsTo(f, 'PUT', '/api/install/settings/backups')).toHaveLength(1));
    expect(callsTo(f, 'PUT', '/api/install/settings/backups')[0].body).toEqual({ at: null });
    unmount();
    wrapBook(<BackupsPanel s={{ ...BACKUPS, at: { ...BACKUPS.at, source: 'env' } }} row={row('backups')} />);
    expect(screen.getByLabelText('Time')).toBeDisabled();
    expect(screen.getByText('Set in your settings file (STEWARD_BACKUP_AT)')).toBeInTheDocument();
  });

  it('never shows the ping URL, only its masked tail as the placeholder, and Remove clears it', async () => {
    const f = stubFetch({ 'PUT /api/install/settings/backups': () => reply({}) });
    wrapBook(<BackupsPanel s={BACKUPS} row={row('backups')} />);
    const input = screen.getByLabelText('Ping URL');
    expect(input).toHaveAttribute('type', 'url');
    expect(input).toHaveAttribute('placeholder', 'hc-ping.example/…9f2c');
    expect(input).toHaveValue('');
    fireEvent.click(screen.getByRole('button', { name: 'Remove the ping URL' }));
    await vi.waitFor(() => expect(callsTo(f, 'PUT', '/api/install/settings/backups')).toHaveLength(1));
    expect(callsTo(f, 'PUT', '/api/install/settings/backups')[0].body).toEqual({ ping_url: null });
  });
});

describe('GatewayPanel', () => {
  it('says the gateway runs on the CPU, once, with a link to the GPU guide', () => {
    wrapBook(<GatewayPanel row={row('ask', { url_set: true, paired: true, state: 'ok', chat_on: true, accelerator: 'cpu' })} onCheck={() => {}} checking={false} />);
    expect(screen.getAllByText(/^Runs on /)).toHaveLength(1);
    expect(screen.getByText('Runs on the CPU.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'A GPU makes it faster' })).toHaveAttribute('href', 'https://github.com/steward-money/steward/blob/main/docs/guides/gpu.md');
  });

  it('names the GPU it runs on, with no link', () => {
    const { unmount } = wrapBook(<GatewayPanel row={row('ask', { url_set: true, paired: true, state: 'ok', chat_on: true, accelerator: 'cuda' })} onCheck={() => {}} checking={false} />);
    expect(screen.getByText('Runs on an NVIDIA GPU.')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'A GPU makes it faster' })).toBeNull();
    unmount();
    wrapBook(<GatewayPanel row={row('ask', { url_set: true, paired: true, state: 'ok', chat_on: true, accelerator: 'rocm' })} onCheck={() => {}} checking={false} />);
    expect(screen.getByText('Runs on an AMD GPU.')).toBeInTheDocument();
  });

  it("shows nothing for a value it doesn't know, or a gateway that isn't answering", () => {
    const { unmount } = wrapBook(<GatewayPanel row={row('ask', { url_set: true, paired: true, state: 'ok', chat_on: true, accelerator: null })} onCheck={() => {}} checking={false} />);
    expect(screen.queryByText(/^Runs on /)).toBeNull();
    unmount();
    wrapBook(<GatewayPanel row={row('ask', { url_set: true, paired: true, state: 'away', chat_on: true, accelerator: 'cpu' })} onCheck={() => {}} checking={false} />);
    expect(screen.queryByText(/^Runs on /)).toBeNull();
  });

  it('Pair again asks first, then shows the Code field', () => {
    stubFetch({});
    wrapBook(<GatewayPanel row={row('ask', { url_set: true, paired: true, state: 'ok', chat_on: true })} onCheck={() => {}} checking={false} />);
    const again = screen.getByRole('button', { name: 'Pair again' });
    again.focus();
    fireEvent.click(again);
    const sheet = screen.getByRole('dialog');
    expect(within(sheet).getByText('Pair again?')).toBeInTheDocument();
    expect(within(sheet).getByText("Ask stops until it's done.")).toBeInTheDocument();
    expect(screen.queryByLabelText('Code')).toBeNull();
    fireEvent.click(within(sheet).getByRole('button', { name: 'Pair' }));
    expect(screen.getByLabelText('Code')).toHaveFocus();   // Pair again itself is gone
  });

  it('offers Check again when a paired gateway is away, and not when it is ok', () => {
    stubFetch({});
    const onCheck = vi.fn();
    const { unmount } = wrapBook(<GatewayPanel row={row('ask', { url_set: true, paired: true, state: 'away', chat_on: true })} onCheck={onCheck} checking={false} />);
    fireEvent.click(screen.getByRole('button', { name: 'Check again' }));
    expect(onCheck).toHaveBeenCalledTimes(1);
    unmount();
    wrapBook(<GatewayPanel row={row('ask', { url_set: true, paired: true, state: 'ok', chat_on: true })} onCheck={onCheck} checking={false} />);
    expect(screen.queryByRole('button', { name: 'Check again' })).toBeNull();
  });

  it("keeps the server's line after the refetch reports paired", async () => {
    stubFetch({ 'POST /api/install/gateway/pair': () => reply({ line: 'Paired with Zebra-Box.' }) });
    function Parent() {
      const [paired, setPaired] = useState(false);
      return <><GatewayPanel row={row('ask', { url_set: true, paired, state: 'ok', chat_on: true })} onCheck={() => {}} checking={false} />
        <button onClick={() => setPaired(true)}>refetched</button></>;
    }
    wrapBook(<Parent />);
    fireEvent.change(screen.getByLabelText('Code'), { target: { value: 'k7m4qx' } });
    fireEvent.click(screen.getByRole('button', { name: 'Pair' }));
    expect(await screen.findByText('Paired with Zebra-Box.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'refetched' }));
    expect(screen.getByText('Paired with Zebra-Box.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Pair again' })).toBeNull();
  });

  it('shows the pairing form when a URL is set and nothing is paired, and a way to turn Ask on when it is off', () => {
    stubFetch({});
    const { unmount } = wrapBook(<GatewayPanel row={row('ask', { url_set: true, paired: false, state: null, chat_on: false })} onCheck={() => {}} checking={false} />);
    expect(screen.getByLabelText('Code')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Turn on' })).toHaveAttribute('href', '/b/ours/settings/chat');
    unmount();
    wrapBook(<GatewayPanel row={row('ask', { url_set: false, paired: false, state: null, chat_on: true })} onCheck={() => {}} checking={false} />);
    expect(screen.queryByLabelText('Code')).toBeNull();
  });
});

describe('StewardSettings', () => {
  it('shows a time zone the settings file owns as read-only; saving the name asks /me again', async () => {
    const f = stubFetch({ 'PUT /api/install/settings/general': () => reply({}) });
    const { qc } = wrapBook(<StewardSettings s={GENERAL} />);
    const spy = vi.spyOn(qc, 'invalidateQueries');
    expect(screen.getByLabelText('Time zone')).toBeDisabled();
    expect(screen.getByLabelText('Time zone')).toHaveValue('America/Los_Angeles');
    expect(screen.getByText('Set in your settings file (STEWARD_TIMEZONE)')).toBeInTheDocument();
    type('Gateway name', 'Den PC');
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await vi.waitFor(() => expect(callsTo(f, 'PUT', '/api/install/settings/general')).toHaveLength(1));
    expect(callsTo(f, 'PUT', '/api/install/settings/general')[0].body).toEqual({ gateway_name: 'Den PC' });
    await vi.waitFor(() => expect(spy).toHaveBeenCalledWith({ queryKey: ['me'] }));
  });
});
