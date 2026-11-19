import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { reply, stubFetch, wrapBook } from '../../test-utils';
import { LiveRegions } from '../../ui/Live';
import { Sheet } from '../../ui/Sheet';
import type { BootLine, InstallSettings, ReadyRow } from './api';
import { BackupsPanel } from './BackupsPanel';
import { EmailPanel } from './EmailPanel';
import { SettingLine } from './SettingLine';
import { StewardSettings } from './StewardSettings';

const EMAIL: InstallSettings['email'] = { source: 'app', env: 'STEWARD_SMTP_*', host: '', port: 465, user: '', from: '', password_set: false, password_unreadable: false };
const BACKUPS: InstallSettings['backups'] = { at: { value: '03:00', source: 'default', env: 'STEWARD_BACKUP_AT' },
  ping_url: { set: false, shown: null, source: 'default', env: 'STEWARD_BACKUP_PING_URL' }, dir: '/data/backups' };
const GENERAL: InstallSettings['general'] = { timezone: { value: 'UTC', source: 'default', env: 'STEWARD_TIMEZONE', running: 'UTC' },
  gateway_name: { value: 'the gateway', source: 'default', env: 'STEWARD_GATEWAY_NAME' } };
const ROW: ReadyRow = { key: 'backups', status: 'done', detail: '', go: null, lines: [], extra: {} };
const LINE: BootLine = { name: 'STEWARD_BASE_URL', line: 'STEWARD_BASE_URL=https://nas.example.com', running: null, note: null, where: 'steward' };

describe('ready status announcements (issue #51)', () => {
  it.each([
    { name: 'email', panel: <EmailPanel s={EMAIL} />, route: 'PUT /api/install/settings/email',
      change: () => fireEvent.change(screen.getByLabelText('Host'), { target: { value: 'smtp.example.com' } }) },
    { name: 'backups', panel: <BackupsPanel s={BACKUPS} row={ROW} />, route: 'PUT /api/install/settings/backups',
      change: () => fireEvent.click(screen.getByRole('switch', { name: 'Off' })) },
    { name: 'general settings', panel: <StewardSettings s={GENERAL} />, route: 'PUT /api/install/settings/general',
      change: () => fireEvent.change(screen.getByLabelText('Gateway name'), { target: { value: 'Den PC' } }) },
  ])('says each $name save through the existing region and keeps the visible confirmation', async ({ panel, route, change }) => {
    stubFetch({ [route]: () => reply({}) });
    const { container } = wrapBook(<LiveRegions>{panel}</LiveRegions>);
    const region = screen.getByTestId('live-said');
    expect(region).toBeEmptyDOMElement();
    change();
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    const saved = await within(container.querySelector('form')!).findByText('Saved.');
    expect(saved).toBeVisible();
    expect(saved).not.toHaveAttribute('role');
    expect(screen.getByTestId('live-said')).toBe(region);
    expect(region).toHaveTextContent('Saved.');
    region.textContent = '';
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(await within(container.querySelector('form')!).findByText('Saved.')).toBeVisible();
    expect(region).toHaveTextContent('Saved.');
  });

  it('says a setting result on mount and when it changes, but not on unchanged or hidden renders', async () => {
    const props = { line: LINE, done: false, checked: true, checking: false, onCheck: vi.fn() };
    const view = (p: typeof props) => <LiveRegions><SettingLine {...p} /></LiveRegions>;
    const { container, rerender } = render(view(props));
    const region = screen.getByTestId('live-said');
    const result = "Not yet. Steward is still running without it. Restart it after saving the file.";
    expect(within(container.querySelector('.ready__line')!).getByText(result)).toBeVisible();
    await waitFor(() => expect(region).toHaveTextContent(result));
    // As in Notice's tests, clear the announcer to detect an unwanted repeat.
    region.textContent = '';
    rerender(view({ ...props }));
    expect(region).toBeEmptyDOMElement();
    rerender(view({ ...props, done: true }));
    expect(await within(container.querySelector('.ready__line')!).findByText('Took effect.')).toBeVisible();
    expect(region.textContent).toBe('Took effect.');
    region.textContent = '';
    rerender(view({ ...props, checked: false }));
    expect(region).toBeEmptyDOMElement();
    expect(screen.queryByText('Took effect.')).toBeNull();
    rerender(view({ ...props, checking: true }));
    expect(region).toBeEmptyDOMElement();
    rerender(view({ ...props, done: true }));
    expect(await within(container.querySelector('.ready__line')!).findByText('Took effect.')).toBeVisible();
    expect(region).toHaveTextContent('Took effect.');
    expect(container.querySelector('.ready__check p')).not.toHaveAttribute('role');
  });

  it('says updated email-test results and keeps errors visible without another live region', async () => {
    let n = 0;
    stubFetch({ 'POST /api/install/email/test': () => n++ === 0 ? reply({ line: 'Test sent. Check your inbox.' })
      : reply({ error: 'The server refused the password.' }, 422) });
    const { container } = wrapBook(<LiveRegions><EmailPanel s={EMAIL} /></LiveRegions>);
    const region = screen.getByTestId('live-said');
    const form = within(container.querySelector('form')!);
    fireEvent.click(screen.getByRole('button', { name: 'Send a test' }));
    expect(await form.findByText('Test sent. Check your inbox.')).toBeVisible();
    expect(region).toHaveTextContent('Test sent. Check your inbox.');
    fireEvent.click(screen.getByRole('button', { name: 'Send a test' }));
    const error = await form.findByText('The server refused the password.');
    expect(error).toBeVisible();
    expect(error).toHaveClass('field__error');
    expect(error).not.toHaveAttribute('role');
    expect(region).toHaveTextContent('The server refused the password.');
    expect(region).not.toHaveTextContent('Test sent.');
  });

  it('does not announce an empty email-test result', async () => {
    stubFetch({ 'POST /api/install/email/test': () => reply({ line: '' }) });
    wrapBook(<LiveRegions><EmailPanel s={EMAIL} /></LiveRegions>);
    fireEvent.click(screen.getByRole('button', { name: 'Send a test' }));
    // Waiting for the request to finish also covers the render with its empty result.
    const button = await screen.findByRole('button', { name: 'Send a test', busy: false });
    expect(button).not.toHaveAttribute('aria-busy');
    expect(screen.getByTestId('live-said')).toBeEmptyDOMElement();
  });

  it('uses the sheet announcer instead of the page announcer and keeps focus on Save', async () => {
    stubFetch({ 'PUT /api/install/settings/email': () => reply({}) });
    const { container } = wrapBook(<LiveRegions><Sheet open onClose={() => {}} title="Email"><EmailPanel s={EMAIL} /></Sheet></LiveRegions>);
    const pageRegion = within(container).getByTestId('live-said');
    const dialog = screen.getByRole('dialog', { name: 'Email' });
    const sheetRegion = within(dialog).getByTestId('live-said');
    const save = within(dialog).getByRole('button', { name: 'Save' });
    save.focus();
    fireEvent.click(save);
    expect(await within(dialog.querySelector('form')!).findByText('Saved.')).toBeVisible();
    expect(sheetRegion).toHaveTextContent('Saved.');
    expect(pageRegion).toBeEmptyDOMElement();
    expect(save).toHaveFocus();
  });
});
