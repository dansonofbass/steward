import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useFakeTimers } from '../../../test-clock';
import { callsTo, reply, stubFetch } from '../../../test-utils';
import { ME, atProfile, profileState } from '../fixtures';

afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });
beforeEach(() => { useFakeTimers(); });
const LEVELS = { two_year: { years: 2, tuition_fees_cents: 415_000, living_cents: 1_717_000 }, in_state_public: { years: 4, tuition_fees_cents: 1_195_000, living_cents: 1_904_000 },
  out_of_state_public: { years: 4, tuition_fees_cents: 3_188_000, living_cents: 1_904_000 }, private: { years: 4, tuition_fees_cents: 4_500_000, living_cents: 2_047_000 } };
const kid = (over = {}) => ({ id: 1, label: 'Ava', birth_year: 2015, cost_level: 'not_sure', account_id: null, monthly_contribution_cents: 0, share_pct: 100,
  covers_living: true, college_start_year: 2033, outlook: { years: 4, total_cents: 0, covered_cents: 0 }, plan529: null, ...over });
const list = (over = {}) => ({ children: [kid()], college: { growth: 0.01, levels: LEVELS }, suggestions: [], plans: [], ...over });
const base = (kids: Record<string, unknown> = list()) => ({ '/api/profile': profileState(), '/api/auth/me': ME, '/api/children': kids, '/api/accounts': { accounts: [] },
  'PATCH /api/children/1': (_u: string, init: RequestInit) => reply({ ...kid(JSON.parse(init.body as string)), undo: 't1' }) });

describe('Kids and college', () => {
  it('adds a kid once name and birth year are valid; No kids shows only with no kids and no 529', async () => {
    const fetchMock = stubFetch({ ...base(list({ children: [] })), 'POST /api/children': () => reply({ ...kid({ id: 9 }), undo: 't' }, 201),
      'POST /api/profile/sections/kids': () => reply(profileState({ kids: { status: 'doesnt_apply' } })) });
    atProfile('/profile/kids/kids');
    expect(await screen.findByRole('button', { name: 'No kids' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Add a kid' }));
    await waitFor(() => expect(screen.getByLabelText('Name')).toHaveFocus());
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Ben' } });
    fireEvent.change(screen.getByLabelText('Birth year'), { target: { value: '2018' } });
    await waitFor(() => expect(callsTo(fetchMock, 'POST', '/api/children')[0]?.body).toEqual({ label: 'Ben', birth_year: 2018 }));
  });

  it('with three kids, each Remove names its kid, so a screen reader\'s button list tells them apart (THO-12)', async () => {
    stubFetch(base(list({ children: [kid(), kid({ id: 2, label: 'Ben', birth_year: 2017 }), kid({ id: 3, label: 'Cy', birth_year: 2019 })] })));
    atProfile('/profile/kids/kids');
    expect(await screen.findByRole('button', { name: 'Remove Ava' })).toHaveTextContent('Remove');
    expect(screen.getByRole('button', { name: 'Remove Ben' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Remove Cy' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Remove' })).toBeNull();
  });

  it('Remove folds the row away with "Removed Ava · Undo", and Undo posts the token', async () => {
    const fetchMock = stubFetch({ ...base(), 'DELETE /api/children/1': () => reply({ undo: 'rm' }), 'POST /api/undo/rm': () => reply({ undone: 0, transaction: null }) });
    atProfile('/profile/kids/kids');
    fireEvent.click(await screen.findByRole('button', { name: 'Remove Ava' }));
    expect(await screen.findByRole('status')).toHaveTextContent('Removed Ava · Undo');
    fireEvent.click(within(screen.getByRole('status')).getByRole('button', { name: 'Undo' }));
    await waitFor(() => expect(callsTo(fetchMock, 'POST', '/api/undo/rm')).toHaveLength(1));
    await act(async () => {});
  });

  it('a failed Undo of "Removed Ava" (409) keeps the toast and its Undo, and says why', async () => {
    const fetchMock = stubFetch({ ...base(), 'DELETE /api/children/1': () => reply({ undo: 'rm' }), 'POST /api/undo/rm': () => reply({ error: 'Changed since.' }, 409) });
    atProfile('/profile/kids/kids');
    fireEvent.click(await screen.findByRole('button', { name: 'Remove Ava' }));
    const toast = () => document.querySelector('.undo-toast') as HTMLElement;
    await waitFor(() => expect(toast()).toHaveTextContent('Removed Ava · Undo'));
    fireEvent.click(within(toast()).getByRole('button', { name: 'Undo' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Changed since.');
    expect(callsTo(fetchMock, 'POST', '/api/undo/rm')).toHaveLength(1);
    expect(toast()).toHaveTextContent('Removed Ava · Undo');
    expect(within(toast()).getByRole('button', { name: 'Undo' })).toBeEnabled();
  });

  it('the card offers Add a kid, which opens the Kids step; so does a No kids card, keeping ?from=plan', async () => {
    stubFetch({ ...base(list({ children: [kid(), kid({ id: 2, label: 'Ben', birth_year: 2018 })] })), '/api/profile': profileState({ kids: { status: 'done' } }) });
    const first = atProfile('/profile/kids');
    expect(await screen.findByRole('link', { name: 'Add a kid' })).toHaveAttribute('href', '/b/ours/profile/kids/kids');
    expect(screen.getByText('Ben · born 2018')).toBeInTheDocument();
    first.unmount();
    vi.unstubAllGlobals();
    stubFetch({ ...base(list({ children: [] })), '/api/profile': profileState({ kids: { status: 'doesnt_apply' } }) });
    const { location } = atProfile('/profile/kids?from=plan');
    const add = await screen.findByRole('link', { name: 'Add a kid' });
    expect(add).toHaveAttribute('href', '/b/ours/profile/kids/kids?from=plan');
    fireEvent.click(add);
    await waitFor(() => expect(location.current.pathname).toBe('/b/ours/profile/kids/kids'));
    expect(await screen.findByRole('button', { name: 'Add a kid' })).toBeInTheDocument();
  });

  it('a viewer gets no Add a kid on the card', async () => {
    stubFetch({ ...base(), '/api/profile': profileState({ kids: { status: 'done' } }) });
    atProfile('/profile/kids', { role: 'viewer' });
    expect(await screen.findByText('Ava · born 2015')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Add a kid' })).toBeNull();
  });

  it('cover: Not sure yet says how it is counted; the share and living costs save and move the line', async () => {
    const fetchMock = stubFetch(base());
    atProfile('/profile/kids/cover');
    expect(await screen.findByRole('heading', { name: 'Ava · college from 2033', level: 3 })).toBeInTheDocument();
    expect(screen.getByText('Counted as in-state public.')).toBeInTheDocument();
    expect(screen.getByText(/^About \$\d{2,3},000 in today's dollars for 4 years\.$/)).toBeInTheDocument();
    fireEvent.change(screen.getByRole('slider'), { target: { value: '0' } });
    expect(await screen.findByText('Nothing for the Plan to set aside for Ava.')).toBeInTheDocument();
    expect(screen.getByText('0%')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('radio', { name: 'Tuition and fees only' }));
    await waitFor(() => expect(callsTo(fetchMock, 'PATCH', '/api/children/1').map((c) => c.body)).toContainEqual(expect.objectContaining({ covers_living: false })));
    fireEvent.change(screen.getByRole('slider'), { target: { value: '100' } });
    await waitFor(() => expect(screen.getByText('100%')).toBeInTheDocument());
  });

  it('529s: a suggestion of another type links and makes it a 529 plan in one call', async () => {
    const data = list({ suggestions: [{ child_id: 1, account_id: 7, account_name: "Ava's college fund", account_type: 'savings' }],
      plans: [{ account_id: 8, name: 'Fidelity 529', balance_cents: 0, connected: false, deposits_monthly_cents: null, real_return: 0.04 }] });
    const fetchMock = stubFetch(base(data));
    atProfile('/profile/kids/plans');
    expect(await screen.findByText("Ava's college fund looks like Ava's. It's set up as Savings.")).toBeInTheDocument();
    expect(screen.getByText("Fidelity 529 isn't linked to a kid, so the Plan waits.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Link it and make it a 529 plan' }));
    await waitFor(() => expect(callsTo(fetchMock, 'PATCH', '/api/children/1')[0]?.body).toEqual({ account_id: 7, set_type: true }));
  });

  it('529s: linking a connected 529 prefills the monthly amount from its deposits and says so', async () => {
    const data = list({ plans: [{ account_id: 8, name: 'Fidelity 529', balance_cents: 1_000_000, connected: true, deposits_monthly_cents: 25_000, real_return: 0.04 }] });
    const fetchMock = stubFetch(base(data));
    atProfile('/profile/kids/plans');
    fireEvent.change(await screen.findByLabelText('Their 529'), { target: { value: '8' } });
    expect(await screen.findByText('From the last 12 months of deposits.')).toBeInTheDocument();
    expect(screen.getByLabelText('Monthly contribution')).toHaveValue('250');
    await waitFor(() => expect(callsTo(fetchMock, 'PATCH', '/api/children/1')[0]?.body).toEqual({ account_id: 8, monthly_contribution_cents: 25_000 }));
    expect(await screen.findByText(/Ava's 529 is on track to cover about \$[\d,]+\.$/)).toBeInTheDocument();
  });

  it('the card lists each kid with what is covered and a pencil that opens their fields', async () => {
    stubFetch({ ...base(list({ children: [kid({ cost_level: 'private', share_pct: 50, covers_living: false })] })),
      '/api/profile': profileState({ kids: { status: 'done' } }) });
    atProfile('/profile/kids');
    expect(await screen.findByText('Ava · born 2015')).toBeInTheDocument();
    expect(screen.getByText('Private (4 years) · 50% · tuition and fees only · No 529')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Edit Ava' }));
    expect(await screen.findByRole('slider')).toHaveValue('50');
    await act(async () => {});
  });
  it('a school or share change shows "Saved · Undo", and Undo posts the token', async () => {
    const fetchMock = stubFetch({ ...base(), 'POST /api/undo/t1': () => reply({ undone: 0, transaction: null }) });
    atProfile('/profile/kids/cover');
    fireEvent.click(await screen.findByRole('radio', { name: 'Private (4 years)' }));
    const undo = await screen.findByRole('button', { name: 'Undo' });
    expect(undo.parentElement).toHaveTextContent('Saved · Undo');
    fireEvent.click(undo);
    await waitFor(() => expect(callsTo(fetchMock, 'POST', '/api/undo/t1')).toHaveLength(1));
    await act(async () => {});
  });

  it('Undo that the server refuses (409) keeps Undo and says why', async () => {
    stubFetch({ ...base(), 'POST /api/undo/t1': () => reply({ error: 'Changed since.' }, 409) });
    atProfile('/profile/kids/cover');
    fireEvent.click(await screen.findByRole('radio', { name: 'Private (4 years)' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Undo' }));
    expect(await screen.findByText(/Changed since/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Undo' })).toBeInTheDocument();
  });

  it('adding a kid offers "Added Ben · Undo"', async () => {
    const fetchMock = stubFetch({ ...base(list({ children: [] })), 'POST /api/children': () => reply({ ...kid({ id: 9 }), undo: 'add' }, 201),
      'POST /api/undo/add': () => reply({ undone: 0, transaction: null }) });
    atProfile('/profile/kids/kids');
    fireEvent.click(await screen.findByRole('button', { name: 'Add a kid' }));
    fireEvent.change(await screen.findByLabelText('Name'), { target: { value: 'Ben' } });
    fireEvent.change(screen.getByLabelText('Birth year'), { target: { value: '2018' } });
    const toast = await screen.findByText('Added Ben', {});
    fireEvent.click(within(toast.parentElement as HTMLElement).getByRole('button', { name: 'Undo' }));
    await waitFor(() => expect(callsTo(fetchMock, 'POST', '/api/undo/add')).toHaveLength(1));
    await act(async () => {});
  });

  it('529 Undo puts the select and the amount back to what the server has', async () => {
    let account: number | null = null;
    const data = () => list({ children: [kid({ account_id: account })], plans: [{ account_id: 8, name: 'Fidelity 529', balance_cents: 0, connected: false, deposits_monthly_cents: null, real_return: 0.04 }] });
    stubFetch({ ...base(), '/api/children': () => reply(data()),
      'PATCH /api/children/1': () => { account = 8; return reply({ ...kid({ account_id: 8 }), undo: 'u' }); },
      'POST /api/undo/u': () => { account = null; return reply({ undone: 0, transaction: null }); } });
    atProfile('/profile/kids/plans');
    const select = await screen.findByLabelText('Their 529');
    fireEvent.change(select, { target: { value: '8' } });
    fireEvent.click(await screen.findByRole('button', { name: 'Undo' }));
    await waitFor(() => expect(screen.getByLabelText('Their 529')).toHaveValue(''));
  });
});
