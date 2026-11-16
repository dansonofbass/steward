import { fireEvent, screen } from '@testing-library/react';
import { Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { callsTo, reply, stubFetch, wrapBook } from '../../test-utils';
import { PARENT, SETTINGS } from './fixtures';
import { Watching } from './Watching';

afterEach(() => vi.unstubAllGlobals());
const mount = (book: Parameters<typeof wrapBook>[1] = PARENT, path = '/b/margaret-ellis/settings/watching') =>
  wrapBook(<Routes><Route path="/b/:slug/settings/:section" element={<Watching />} /><Route path="/b/:slug/settings/:section/:step" element={<Watching />} /></Routes>, book, path);

describe('Settings → Watching', () => {
  it('reads like the mockup', async () => {
    stubFetch({ '/api/watching': SETTINGS });
    mount();
    expect(await screen.findByText("What the checks flag in Margaret's accounts, and who is emailed. Changes apply to new transactions from now on; old ones aren't checked again.")).toBeInTheDocument();
    expect(screen.getByLabelText('Flag money out of')).toHaveValue('500');
    expect(screen.getByText('Any payment of this much or more is flagged, unless the payee is in Known payees. Default $500.00.')).toBeInTheDocument();
    expect(screen.getByLabelText('Floor for Way2Save savings')).toHaveValue('25,000');
    expect(screen.getByLabelText('Floor for 12-month CD')).toHaveValue('');
    expect(screen.getByText('under its floor')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /1 known payee/ })).toHaveAttribute('href', '/b/margaret-ellis/settings/watching/known');
    expect(screen.getByText('Email is set up.')).toBeInTheDocument();
    expect(screen.getByText('Last sent today at 7:00 AM (daily summary to JR and Robin).')).toBeInTheDocument();
    expect(screen.getByRole('switch', { name: 'Urgent emails for JR' })).toHaveAttribute('aria-checked', 'true');
    expect(screen.getByRole('switch', { name: 'Urgent emails for Robin' })).toBeDisabled();
    expect(screen.getByRole('switch', { name: 'Daily summary for Tess' })).toHaveAttribute('aria-checked', 'false');
  });
  it('saves the cash alert floor', async () => {
    const fetchMock = stubFetch({
      '/api/watching': SETTINGS,
      'PATCH /api/watching/cash-floor': () => reply({ ...SETTINGS, cash_alert_floor_cents: 30000 }),
    });
    mount();
    const input = await screen.findByLabelText('Alert on cash from');
    expect(input).toHaveValue('200');
    fireEvent.change(input, { target: { value: '300.00' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await vi.waitFor(() => expect(callsTo(fetchMock, 'PATCH', '/api/watching/cash-floor')[0]?.body).toEqual({ cents: 30000 }));
  });
  it('saves the large amount, a floor and a switch, and shows the last-manager refusal', async () => {
    const fetchMock = stubFetch({
      '/api/watching': SETTINGS,
      'PATCH /api/watching/large': () => reply({ ...SETTINGS, large_cents: 75000 }),
      'PUT /api/watching/floors/3': () => reply(SETTINGS),
      'PATCH /api/watching/emails/3': () => reply(SETTINGS),
      'PATCH /api/watching/emails/1': () => reply({ error: 'At least one manager has to get urgent emails. Turn them on for another manager first.' }, 409),
    });
    mount();
    fireEvent.change(await screen.findByLabelText('Flag money out of'), { target: { value: '750.00' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await vi.waitFor(() => expect(callsTo(fetchMock, 'PATCH', '/api/watching/large')[0]?.body).toEqual({ cents: 75000 }));
    const cd = screen.getByLabelText('Floor for 12-month CD');
    fireEvent.change(cd, { target: { value: '10,000.00' } });
    fireEvent.blur(cd);
    await vi.waitFor(() => expect(callsTo(fetchMock, 'PUT', '/api/watching/floors/3')[0]?.body).toEqual({ cents: 1000000 }));
    await vi.waitFor(() => expect(screen.getByRole('switch', { name: 'Urgent emails for Tess' })).toBeEnabled());
    fireEvent.click(screen.getByRole('switch', { name: 'Urgent emails for Tess' }));
    await vi.waitFor(() => expect(callsTo(fetchMock, 'PATCH', '/api/watching/emails/3')[0]?.body).toEqual({ urgent: true }));
    await vi.waitFor(() => expect(screen.getByRole('switch', { name: 'Urgent emails for JR' })).toBeEnabled());
    fireEvent.click(screen.getByRole('switch', { name: 'Urgent emails for JR' }));
    expect(await screen.findByText('At least one manager has to get urgent emails. Turn them on for another manager first.')).toBeInTheDocument();
  });
  it("says when email isn't set up, and shows a failed urgent email", async () => {
    stubFetch({ '/api/watching': { ...SETTINGS, mail: { ready: false, last_sent: null, failure: {
      title: "An urgent email couldn't be sent.",
      line: '"$500.00 gift card at CVS Pharmacy" to JR and Robin, Oct 18. Tried 3 times until 7:14 AM; the mail server said: "535 authentication failed".' } } } });
    mount();
    expect(await screen.findByText("Email isn't set up.")).toBeInTheDocument();
    expect(screen.getByText(/add the SMTP settings to Steward's settings file and restart Steward/)).toBeInTheDocument();
    expect(screen.getByText("An urgent email couldn't be sent.")).toBeInTheDocument();
    expect(screen.getByText('The flag is still open in Look into. This notice stays until an email goes through.')).toBeInTheDocument();
  });
  it('a viewer reads it, and can stop their own emails', async () => {
    const viewerView = { ...SETTINGS, can_edit: false, people: SETTINGS.people.map((p) => ({ ...p, can_change: false, is_me: p.name === 'Tess', urgent: p.name === 'Tess' ? true : p.urgent })) };
    const fetchMock = stubFetch({ '/api/watching': viewerView, 'POST /api/watching/emails/stop': () => reply(SETTINGS) });
    mount({ ...PARENT, role: 'viewer' });
    expect(await screen.findByLabelText('Flag money out of')).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'Send me a test email' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Stop my emails' }));
    await vi.waitFor(() => expect(callsTo(fetchMock, 'POST', '/api/watching/emails/stop')).toHaveLength(1));
  });
  it("shows the notice when email isn't set up and locks the switches a person can't change", async () => {
    const locked = { ...SETTINGS, mail: { ready: false, last_sent: null, failure: null },
      people: SETTINGS.people.map((p) => ({ ...p, can_change: false })) };
    stubFetch({ '/api/watching': locked });
    mount();
    expect(await screen.findByText("Email isn't set up.")).toBeInTheDocument();
    expect(screen.queryByText('Email is set up.')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Send me a test email' })).toBeNull();
    for (const name of ['JR', 'Robin', 'Tess']) {
      expect(screen.getByRole('switch', { name: `Urgent emails for ${name}` })).toBeDisabled();
      expect(screen.getByRole('switch', { name: `Daily summary for ${name}` })).toBeDisabled();
    }
  });
  it('sends a test email', async () => {
    stubFetch({ '/api/watching': SETTINGS, 'POST /api/watching/test-email': () => reply({ sent_to: 'jr@example.com' }) });
    mount();
    fireEvent.click(await screen.findByRole('button', { name: 'Send me a test email' }));
    expect(await screen.findByText('Sent to jr@example.com.')).toBeInTheDocument();
  });
  it('keeps what was typed when the large amount fails to save', async () => {
    stubFetch({ '/api/watching': SETTINGS, 'PATCH /api/watching/large': () => reply({ error: 'That is more than the limit.' }, 422) });
    mount();
    fireEvent.change(await screen.findByLabelText('Flag money out of'), { target: { value: '9999999' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(await screen.findByText('That is more than the limit.')).toBeInTheDocument();
    expect(screen.getByLabelText('Flag money out of')).toHaveValue('9,999,999');
    expect(screen.getByRole('button', { name: 'Save' })).toBeInTheDocument();
  });
  it('keeps what was typed when a floor fails to save', async () => {
    stubFetch({ '/api/watching': SETTINGS, 'PUT /api/watching/floors/3': () => reply({ error: 'Could not save the floor.' }, 500) });
    mount();
    const cd = await screen.findByLabelText('Floor for 12-month CD');
    fireEvent.change(cd, { target: { value: '10,000.00' } });
    fireEvent.blur(cd);
    expect(await screen.findByText('Could not save the floor.')).toBeInTheDocument();
    expect(screen.getByLabelText('Floor for 12-month CD')).toHaveValue('10,000.00');
  });
  it('keeps a second edit made while the first floor save is running', async () => {
    let finish!: () => void;
    stubFetch({ '/api/watching': SETTINGS, 'PUT /api/watching/floors/3': () => new Promise<Response>((res) => { finish = () => res(reply(SETTINGS)); }) });
    mount();
    const cd = await screen.findByLabelText('Floor for 12-month CD');
    fireEvent.change(cd, { target: { value: '10,000' } });
    fireEvent.blur(cd);
    fireEvent.change(screen.getByLabelText('Floor for 12-month CD'), { target: { value: '12,000' } });
    finish();
    await vi.waitFor(() => expect(screen.getByRole('switch', { name: 'Urgent emails for Tess' })).toBeEnabled());
    expect(screen.getByLabelText('Floor for 12-month CD')).toHaveValue('12,000');
  });
  it('clears a floor typed with stray spaces once it saves', async () => {
    stubFetch({ '/api/watching': SETTINGS, 'PUT /api/watching/floors/3': () => reply(SETTINGS) });
    mount();
    const cd = await screen.findByLabelText('Floor for 12-month CD');
    fireEvent.change(cd, { target: { value: ' 10,000 ' } });
    fireEvent.blur(cd);
    await vi.waitFor(() => expect(screen.getByLabelText('Floor for 12-month CD')).toHaveValue(''));
  });
  it('keeps a second edit made while the large amount is saving', async () => {
    let finish!: () => void;
    stubFetch({ '/api/watching': SETTINGS, 'PATCH /api/watching/large': () => new Promise<Response>((res) => { finish = () => res(reply({ ...SETTINGS, large_cents: 75000 })); }) });
    mount();
    fireEvent.change(await screen.findByLabelText('Flag money out of'), { target: { value: '750' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    fireEvent.change(screen.getByLabelText('Flag money out of'), { target: { value: '800' } });
    finish();
    await vi.waitFor(() => expect(screen.getByRole('switch', { name: 'Urgent emails for Tess' })).toBeEnabled());
    expect(screen.getByLabelText('Flag money out of')).toHaveValue('800');
  });
  it('saves a floor once when Enter is followed by the blur', async () => {
    const fetchMock = stubFetch({ '/api/watching': SETTINGS, 'PUT /api/watching/floors/3': () => new Promise(() => {}) });
    mount();
    const cd = await screen.findByLabelText('Floor for 12-month CD');
    fireEvent.change(cd, { target: { value: '10,000.00' } });
    fireEvent.keyDown(cd, { key: 'Enter' });
    fireEvent.blur(cd);
    expect(callsTo(fetchMock, 'PUT', '/api/watching/floors/3')).toHaveLength(1);
  });
  it("does not show a viewer the how-to for setting email up, which they can't act on", async () => {
    const viewerView = { ...SETTINGS, can_edit: false, mail: { ready: false, last_sent: null, failure: null },
      people: SETTINGS.people.map((p) => ({ ...p, can_change: false })) };
    stubFetch({ '/api/watching': viewerView });
    mount({ ...PARENT, role: 'viewer' });
    expect(await screen.findByText("Email isn't set up.")).toBeInTheDocument();
    expect(screen.queryByText(/add the SMTP settings/)).toBeNull();
  });
});
