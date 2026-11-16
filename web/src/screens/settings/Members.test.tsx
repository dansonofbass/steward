import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { callsTo, expectRemovalSaid, reply, stubFetch, wrapBook } from '../../test-utils';
import Members from './Members';

afterEach(() => vi.unstubAllGlobals());
const MOM = { slug: 'mom', name: 'Mom', kind: 'parent' as const, owners: [] };
const ME = { user: { id: 1, username: 'jr', display_name: 'JR' }, session: { id: 1, device_label: '', created_at: '' }, books: [] };
const MEMBERS = { members: [
  { user_id: 1, username: 'jr', display_name: 'JR', email: 'jr@example.com', role: 'manager' },
  { user_id: 3, username: 'vee', display_name: 'Vee', email: 'vee@example.com', role: 'viewer' }] };
const USERS = { users: [{ id: 1, username: 'jr', display_name: 'JR', can_reset: false }, { id: 2, username: 'sam', display_name: 'Sam', can_reset: true }] };
const INVITED = { status: 'Invited', invite_id: '7', email: 'pat@example.com', role: 'viewer', user_id: null, username: null, display_name: null };

describe('Settings, Book members', () => {
  it('a manager invites someone, changes a role and sees the server\'s refusal', async () => {
    const fetchMock = stubFetch({
      '/api/auth/me': ME, '/api/books/mom/members': MEMBERS,
      'POST /api/books/mom/members': () => reply({ member: { user_id: 4, username: 'wren', display_name: 'Wren', email: 'wren@example.com', role: 'viewer' }, invited: true }, 201),
      'PATCH /api/books/mom/members/1': () => reply({ error: 'A book needs at least one manager.' }, 409),
    });
    wrapBook(<Members />, MOM, '/b/mom/settings/members');
    expect(await screen.findByText('vee@example.com')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Invite someone' }));
    const sheet = screen.getByRole('dialog', { name: 'Invite someone' });
    fireEvent.change(within(sheet).getByLabelText('Email'), { target: { value: 'wren@example.com' } });
    fireEvent.change(within(sheet).getByLabelText('Name'), { target: { value: 'Wren' } });
    expect(within(sheet).getByLabelText('Role')).toHaveValue('viewer');
    fireEvent.click(within(sheet).getByRole('button', { name: 'Invite' }));
    expect(await screen.findByText('Invite sent to wren@example.com.')).toBeInTheDocument();
    expect(callsTo(fetchMock, 'POST', '/api/books/mom/members')[0].body).toEqual({ email: 'wren@example.com', display_name: 'Wren', role: 'viewer' });
    fireEvent.change(screen.getByLabelText('Role, JR'), { target: { value: 'viewer' } });
    fireEvent.click(within(screen.getByRole('dialog', { name: 'Make yourself a viewer of Mom?' })).getByRole('button', { name: 'Make viewer' }));
    expect(await screen.findByText('A book needs at least one manager.')).toBeInTheDocument();
  });
  it('the invite line reads the same when the server answers with only the typed email', async () => {
    stubFetch({
      '/api/auth/me': ME, '/api/books/mom/members': MEMBERS,
      'POST /api/books/mom/members': () => reply({ member: { email: 'jr@example.com', role: 'viewer', status: 'Invited' }, invited: true }, 201),
    });
    wrapBook(<Members />, MOM, '/b/mom/settings/members');
    fireEvent.click(await screen.findByRole('button', { name: 'Invite someone' }));
    const sheet = screen.getByRole('dialog', { name: 'Invite someone' });
    fireEvent.change(within(sheet).getByLabelText('Email'), { target: { value: 'jr@example.com' } });
    fireEvent.click(within(sheet).getByRole('button', { name: 'Invite' }));
    expect(await screen.findByText('Invite sent to jr@example.com.')).toBeInTheDocument();
  });
  it('with email off, an install manager sees the text to send and can copy it', async () => {
    const writeText = vi.fn(async () => {});
    vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } });
    stubFetch({
      '/api/auth/me': ME, '/api/books/mom/members': MEMBERS,
      'POST /api/books/mom/members': () => reply({ member: { email: 'sam@example.com', role: 'viewer', status: 'Invited' }, invited: true, send_yourself: 'Hi Sam, join at /invite?token=x' }, 201),
    });
    wrapBook(<Members />, MOM, '/b/mom/settings/members');
    fireEvent.click(await screen.findByRole('button', { name: 'Invite someone' }));
    const sheet = screen.getByRole('dialog', { name: 'Invite someone' });
    fireEvent.change(within(sheet).getByLabelText('Email'), { target: { value: 'sam@example.com' } });
    fireEvent.click(within(sheet).getByRole('button', { name: 'Invite' }));
    expect(await screen.findByText("Email isn't set up, so send this to sam@example.com yourself.")).toBeInTheDocument();
    const text = screen.getByRole('textbox');
    expect(text).toHaveValue('Hi Sam, join at /invite?token=x');
    expect(text).toHaveAttribute('readonly');
    fireEvent.click(screen.getByRole('button', { name: 'Copy' }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith('Hi Sam, join at /invite?token=x'));
    expect(await within(sheet).findByRole('status')).toHaveTextContent('Copied');      // said beside the button (WEB-21)
    fireEvent.click(screen.getByRole('button', { name: 'Done' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(screen.queryByText(/Invite sent/)).toBeNull();
  });
  it('with email off, anyone else is told plainly', async () => {
    stubFetch({
      '/api/auth/me': ME, '/api/books/mom/members': MEMBERS,
      'POST /api/books/mom/members': () => reply({ member: { email: 'sam@example.com', role: 'viewer', status: 'Invited' }, invited: true, mail_off: true }, 201),
    });
    wrapBook(<Members />, MOM, '/b/mom/settings/members');
    fireEvent.click(await screen.findByRole('button', { name: 'Invite someone' }));
    const sheet = screen.getByRole('dialog', { name: 'Invite someone' });
    fireEvent.change(within(sheet).getByLabelText('Email'), { target: { value: 'sam@example.com' } });
    fireEvent.click(within(sheet).getByRole('button', { name: 'Invite' }));
    expect(await screen.findByText("Email isn't set up, so the invite wasn't sent. A manager of the household can set it up.")).toBeInTheDocument();
    expect(screen.queryByText(/Invite sent/)).toBeNull();
  });
  it('a manager sees the page under Book members, without the book name (This book has it now)', async () => {
    stubFetch({ '/api/auth/me': ME, '/api/books/mom/members': MEMBERS });
    wrapBook(<Members />, MOM, '/b/mom/settings/members');
    expect(await screen.findByRole('heading', { level: 2, name: 'Book members' })).toBeInTheDocument();
    expect(screen.queryByRole('textbox', { name: 'Name' })).toBeNull();
  });
  it('a viewer sees the members, and nothing to change', async () => {
    stubFetch({ '/api/auth/me': ME, '/api/books/mom/members': MEMBERS });
    wrapBook(<Members />, { ...MOM, role: 'viewer' }, '/b/mom/settings/members');
    expect(await screen.findByText('vee@example.com')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Invite someone' })).toBeNull();
    expect(screen.queryByLabelText('Role, JR')).toBeNull();
  });
  it('removing someone asks first and says what they lose and what stays', async () => {
    const fetchMock = stubFetch({ '/api/auth/me': ME, '/api/books/mom/members': MEMBERS, 'DELETE /api/books/mom/members/3': () => new Response(null, { status: 204 }) });
    wrapBook(<Members />, MOM, '/b/mom/settings/members');
    fireEvent.click(await screen.findByRole('button', { name: 'Remove Vee' }));
    const ask = screen.getByRole('dialog', { name: 'Remove Vee from Mom?' });
    expect(within(ask).getByText('Vee can no longer open Mom, and any Claude Code grant they hold for it ends. Everything in Mom stays, including what Vee entered. A manager can invite them back.')).toBeInTheDocument();
    expect(callsTo(fetchMock, 'DELETE', '/api/books/mom/members')).toHaveLength(0);
    fireEvent.click(within(ask).getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByRole('dialog')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Remove Vee' }));
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Remove' }));
    await screen.findByText('vee@example.com');
    expect(callsTo(fetchMock, 'DELETE', '/api/books/mom/members/3')).toHaveLength(1);
  });
  it('after removing someone, says who went and keeps focus on the list, not the gone row (THO-1)', async () => {
    let members = MEMBERS;
    stubFetch({ '/api/auth/me': ME, '/api/books/mom/members': () => reply(members),
      'DELETE /api/books/mom/members/3': () => { members = { members: [MEMBERS.members[0]] }; return new Response(null, { status: 204 }); } });
    wrapBook(<Members />, MOM, '/b/mom/settings/members');
    const button = await screen.findByRole('button', { name: 'Remove Vee' });
    button.focus();
    fireEvent.click(button);
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Remove' }));
    await expectRemovalSaid('Removed Vee from Mom.', () => screen.getByRole('heading', { name: 'People' }));
    expect(screen.queryByText('vee@example.com')).toBeNull();
  });
  it('removing two people with the same name says the line each time (THO-1)', async () => {
    const vee2 = { user_id: 5, username: 'vee2', display_name: 'Vee', email: 'vee2@example.com', role: 'viewer' };
    let members = { members: [...MEMBERS.members, vee2] };
    const drop = (id: number) => () => { members = { members: members.members.filter((m) => m.user_id !== id) }; return new Response(null, { status: 204 }); };
    stubFetch({ '/api/auth/me': ME, '/api/books/mom/members': () => reply(members),
      'DELETE /api/books/mom/members/3': drop(3), 'DELETE /api/books/mom/members/5': drop(5) });
    wrapBook(<Members />, MOM, '/b/mom/settings/members');
    await screen.findByText('vee2@example.com');
    fireEvent.click(screen.getAllByRole('button', { name: 'Remove Vee' })[0]);
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Remove' }));
    await expectRemovalSaid('Removed Vee from Mom.', () => screen.getByRole('heading', { name: 'People' }));
    await waitFor(() => expect(screen.getAllByRole('button', { name: 'Remove Vee' })).toHaveLength(1));
    const first = screen.getByText('Removed Vee from Mom.');
    const region = first.closest('[aria-live="polite"]')!;
    let changes = 0;
    const seen = new MutationObserver((records) => { changes += records.length; });
    seen.observe(region, { childList: true, subtree: true, characterData: true });
    fireEvent.click(screen.getByRole('button', { name: 'Remove Vee' }));
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Remove' }));
    await waitFor(() => expect(screen.queryByText('vee2@example.com')).toBeNull());
    await waitFor(() => expect(changes + seen.takeRecords().length).toBeGreaterThan(0));
    expect(screen.getByText('Removed Vee from Mom.')).not.toBe(first);
    seen.disconnect();
  });
  it('after cancelling an invite, says so and keeps focus on the list (THO-1)', async () => {
    let members = { members: [...MEMBERS.members, INVITED] };
    stubFetch({ '/api/auth/me': ME, '/api/books/mom/members': () => reply(members),
      'DELETE /api/books/mom/invites/7': () => { members = MEMBERS; return new Response(null, { status: 204 }); } });
    wrapBook(<Members />, MOM, '/b/mom/settings/members');
    const button = await screen.findByRole('button', { name: 'Cancel pat@example.com' });
    button.focus();
    fireEvent.click(button);
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Cancel invitation' }));
    await expectRemovalSaid('Cancelled the invitation to pat@example.com.', () => screen.getByRole('heading', { name: 'People' }));
  });
  it('a cancelled removal gives focus back to the row\'s own button', async () => {
    stubFetch({ '/api/auth/me': ME, '/api/books/mom/members': MEMBERS });
    wrapBook(<Members />, MOM, '/b/mom/settings/members');
    const button = await screen.findByRole('button', { name: 'Remove Vee' });
    button.focus();
    fireEvent.click(button);
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Cancel' }));
    expect(screen.getByRole('button', { name: 'Remove Vee' })).toHaveFocus();
  });
  it('removing yourself names the book, says a manager can invite you back, and needs the second click', async () => {
    const fetchMock = stubFetch({ '/api/auth/me': ME, '/api/books/mom/members': MEMBERS, 'DELETE /api/books/mom/members/1': () => new Response(null, { status: 204 }) });
    wrapBook(<Members />, MOM, '/b/mom/settings/members');
    fireEvent.click(await screen.findByRole('button', { name: 'Remove JR' }));
    const ask = screen.getByRole('dialog', { name: 'Remove yourself from Mom?' });
    expect(within(ask).getByText('You can no longer open Mom. Everything in it stays for the other members, and a manager can invite you back.')).toBeInTheDocument();
    expect(callsTo(fetchMock, 'DELETE', '/api/books/mom/members')).toHaveLength(0);
    fireEvent.click(within(ask).getByRole('button', { name: 'Remove me from Mom' }));
    await waitFor(() => expect(callsTo(fetchMock, 'DELETE', '/api/books/mom/members/1')).toHaveLength(1));
  });
  it('changing a role asks first, says what the role can do, and saves nothing on Cancel', async () => {
    const fetchMock = stubFetch({
      '/api/auth/me': ME, '/api/books/mom/members': MEMBERS,
      'PATCH /api/books/mom/members/3': () => reply({ member: { ...MEMBERS.members[1], role: 'manager' } }),
    });
    wrapBook(<Members />, MOM, '/b/mom/settings/members');
    await screen.findByText('vee@example.com');
    fireEvent.change(screen.getByLabelText('Role, Vee'), { target: { value: 'manager' } });
    const ask = screen.getByRole('dialog', { name: 'Make Vee a manager of Mom?' });
    expect(within(ask).getByText('Vee can then change anything in Mom: accounts, the plan, members and roles.')).toBeInTheDocument();
    fireEvent.click(within(ask).getByRole('button', { name: 'Cancel' }));
    expect(callsTo(fetchMock, 'PATCH', '/api/books/mom/members')).toHaveLength(0);
    expect(screen.getByLabelText('Role, Vee')).toHaveValue('viewer');
    fireEvent.change(screen.getByLabelText('Role, Vee'), { target: { value: 'manager' } });
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Make manager' }));
    await waitFor(() => expect(callsTo(fetchMock, 'PATCH', '/api/books/mom/members/3')).toHaveLength(1));
    expect(callsTo(fetchMock, 'PATCH', '/api/books/mom/members/3')[0].body).toEqual({ role: 'manager' });
  });
  it('making yourself a viewer says only another manager can undo it', async () => {
    stubFetch({ '/api/auth/me': ME, '/api/books/mom/members': MEMBERS });
    wrapBook(<Members />, MOM, '/b/mom/settings/members');
    await screen.findByText('vee@example.com');
    fireEvent.change(screen.getByLabelText('Role, JR'), { target: { value: 'viewer' } });
    const ask = screen.getByRole('dialog', { name: 'Make yourself a viewer of Mom?' });
    expect(within(ask).getByText('You still see everything in Mom and can no longer change anything. Only another manager can make you a manager again.')).toBeInTheDocument();
  });
  it('a manager sees pending invites as Invited rows and can cancel one', async () => {
    const fetchMock = stubFetch({
      '/api/auth/me': ME, '/api/books/mom/members': { members: [...MEMBERS.members, INVITED] },
      'DELETE /api/books/mom/invites/7': () => new Response(null, { status: 204 }),
    });
    wrapBook(<Members />, MOM, '/b/mom/settings/members');
    const email = await screen.findByText('pat@example.com');
    const row = email.closest('.line') as HTMLElement;
    expect(within(row).getByText('Invited')).toBeInTheDocument();
    expect(within(row).queryByLabelText(/^Role/)).toBeNull();
    fireEvent.click(within(row).getByRole('button', { name: 'Cancel pat@example.com' }));
    const ask = screen.getByRole('dialog', { name: "Cancel pat@example.com's invitation?" });
    expect(within(ask).getByText('The link in their email stops working. Nothing else changes, and you can invite them again.')).toBeInTheDocument();
    expect(callsTo(fetchMock, 'DELETE', '/api/books/mom/invites')).toHaveLength(0);
    fireEvent.click(within(ask).getByRole('button', { name: 'Keep it' }));
    expect(screen.queryByRole('dialog')).toBeNull();
    fireEvent.click(within(row).getByRole('button', { name: 'Cancel pat@example.com' }));
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Cancel invitation' }));
    await waitFor(() => expect(callsTo(fetchMock, 'DELETE', '/api/books/mom/invites/7')).toHaveLength(1));
  });
  it('a viewer gets no Invited rows to cancel', async () => {
    stubFetch({ '/api/auth/me': ME, '/api/books/mom/members': MEMBERS });
    wrapBook(<Members />, { ...MOM, role: 'viewer' }, '/b/mom/settings/members');
    await screen.findByText('vee@example.com');
    expect(screen.queryByText('Invited')).toBeNull();
  });
  it("resetting someone's password says up front that they're signed out everywhere, lose their passkeys and their Claude Code grants end", async () => {
    stubFetch({ '/api/auth/me': ME, '/api/books/mom/members': MEMBERS, '/api/users': USERS, 'POST /api/users/2/reset-password': () => new Response(null, { status: 204 }) });
    wrapBook(<Members />, MOM, '/b/mom/settings/members');
    fireEvent.click(await screen.findByRole('button', { name: "Reset Sam's password" }));
    const sheet = screen.getByRole('dialog', { name: "Reset Sam's password" });
    expect(within(sheet).getByText('Sam is signed out everywhere, their passkeys are removed and any Claude Code grants they hold end. They sign in with the new password and add their devices again.')).toBeInTheDocument();
    fireEvent.change(within(sheet).getByLabelText('New password'), { target: { value: 'a-brand-new-password-1' } });
    fireEvent.change(within(sheet).getByLabelText('Your password'), { target: { value: 'mine' } });
    fireEvent.click(within(sheet).getByRole('button', { name: 'Save' }));
    expect(await screen.findByText("Sam's password is changed. They were signed out everywhere, their Claude Code grants ended, and they will add their passkeys again.")).toBeInTheDocument();
  });
});
