import { fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useFakeTimers } from '../../test-clock';
import { callsTo, reply, stubFetch } from '../../test-utils';
import { FACTS, ME, atProfile, profileState } from './fixtures';

afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });
beforeEach(() => { useFakeTimers(); });
const routes = (over = {}) => ({
  '/api/profile': profileState(), '/api/facts': FACTS, '/api/auth/me': ME,
  'POST /api/facts': () => reply({ key: 'x', value: 'x', as_of: '2026-10-13', note: null, undo: 'tok' }, 201),
  'PUT /api/profile/sections/you/resume': () => reply(profileState({ you: { resume_step: 'pay' } })),
  ...over,
});

describe('the guided flow', () => {
  it('a choice saves at once; Next records the resume point and moves on', async () => {
    const fetchMock = stubFetch(routes());
    const { location } = atProfile('/profile/you/taxes');
    expect(await screen.findByRole('heading', { name: 'Taxes', level: 2 })).toBeInTheDocument();
    expect(screen.getByRole('img', { name: 'Step 3 of 4' })).toBeInTheDocument();
    fireEvent.change(await screen.findByLabelText('State'), { target: { value: 'OR' } });
    await waitFor(() => expect(callsTo(fetchMock, 'POST', '/api/facts')[0]?.body).toMatchObject({ key: 'state', value: 'OR' }));
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    await waitFor(() => expect(location.current.pathname).toBe('/b/ours/profile/you/pay'));
    expect(callsTo(fetchMock, 'PUT', '/api/profile/sections/you/resume')[0].body).toEqual({ step: 'pay' });
  });

  it('typed text saves 600 ms after the typing stops', async () => {
    const fetchMock = stubFetch(routes());
    atProfile('/profile/you/pay');
    const salary = await screen.findByLabelText("JR's yearly salary, before deductions");
    fireEvent.change(salary, { target: { value: '170000' } });
    expect(callsTo(fetchMock, 'POST', '/api/facts')).toHaveLength(0);
    await waitFor(() => expect(callsTo(fetchMock, 'POST', '/api/facts')[0]?.body).toMatchObject({ key: 'jr.salary_cents', value: '17000000' }));
  });

  it("Next waits on a failed save, with the server's words under the field and the value as typed", async () => {
    const fetchMock = stubFetch(routes({ 'POST /api/facts': () => reply({ error: 'Enter a date like 2026-10-12.' }, 422) }));
    const { location } = atProfile('/profile/you/you');
    const dob = await screen.findByLabelText('Your birthday');
    fireEvent.change(dob, { target: { value: '1983-01-02' } });
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    expect(await screen.findByText('Enter a date like 2026-10-12.')).toBeInTheDocument();
    expect(dob).toHaveValue('1983-01-02');
    expect(callsTo(fetchMock, 'PUT', '/api/profile/sections/you/resume')).toHaveLength(0);
    expect(location.current.pathname).toBe('/b/ours/profile/you/you');
  });

  it('Done answers done, or Skipped when data is missing, and goes back where it came from', async () => {
    const fetchMock = stubFetch(routes({
      'POST /api/profile/sections/you': (_u: string, init: RequestInit) => (JSON.parse(init.body as string).status === 'done'
        ? reply({ error: 'Still needed: the match cap.' }, 409)
        : reply(profileState({ you: { status: 'skipped', missing: 'the match cap' } }))),
    }));
    const { location } = atProfile('/profile/you/pay?from=plan');
    fireEvent.click(await screen.findByRole('button', { name: 'Done' }));
    await waitFor(() => expect(location.current.pathname).toBe('/b/ours/plan'));
    expect(callsTo(fetchMock, 'POST', '/api/profile/sections/you').map((c) => c.body)).toEqual([{ status: 'done' }, { status: 'skipped' }]);
  });

  it('Skip on the last step answers Skipped; Back shows from step 2 on', async () => {
    const fetchMock = stubFetch(routes({ 'POST /api/profile/sections/you': () => reply(profileState({ you: { status: 'skipped' } })) }));
    const { location } = atProfile('/profile/you/pay');
    expect(await screen.findByRole('link', { name: 'Back' })).toHaveAttribute('href', '/b/ours/profile/you/taxes');
    fireEvent.click(screen.getByRole('button', { name: 'Skip' }));
    await waitFor(() => expect(location.current.pathname).toBe('/b/ours/profile'));
    expect(callsTo(fetchMock, 'POST', '/api/profile/sections/you')[0].body).toEqual({ status: 'skipped' });
  });

  it('an unfinished section with no step opens its resume point', async () => {
    stubFetch(routes({ '/api/profile': profileState({ you: { resume_step: 'taxes' } }) }));
    const { location } = atProfile('/profile/you');
    await waitFor(() => expect(location.current.pathname).toBe('/b/ours/profile/you/taxes'));
  });
});
