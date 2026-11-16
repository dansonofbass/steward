import { fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { callsTo, reply, stubFetch } from '../../../test-utils';
import { FACTS, ME, atProfile, profileState } from '../fixtures';

afterEach(() => vi.unstubAllGlobals());

describe('You and your partner', () => {
  it("the partner's name is read-only, saying who can change it", async () => {
    stubFetch({ '/api/profile': profileState(), '/api/facts': FACTS, '/api/auth/me': ME });
    atProfile('/profile/you/partner');
    expect(await screen.findByRole('heading', { name: 'Alex', level: 2 })).toBeInTheDocument();
    expect(await screen.findByLabelText("Alex's name in Steward")).toHaveAttribute('readonly');
    expect(screen.getByText('Only Alex can change this.')).toBeInTheDocument();
  });

  it('Pay says why, and the employer match follows the typing in dollars', async () => {
    stubFetch({ '/api/profile': profileState(), '/api/facts': FACTS, '/api/auth/me': ME });
    atProfile('/profile/you/pay');
    expect(await screen.findByText('Bank deposits show pay after tax and 401(k), so Steward needs the figures from a pay stub.')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Match rate'), { target: { value: '50' } });
    fireEvent.change(screen.getByLabelText('Match cap'), { target: { value: '6' } });
    expect(await screen.findByText('The employer adds $4,950 a year.')).toBeInTheDocument();   // $165,000 x 6% x 50%
    expect(screen.getByText("Enter 0 if there's no Roth 401(k).")).toBeInTheDocument();
  });

  it("on the partner's first visit their own fields are highlighted, and Confirm marks it", async () => {
    const done = profileState({ you: { status: 'done', by_id: 1, by: 'JR', at: '2026-10-14T18:00:00Z' } }, { user_id: 2, role: 'spouse' });
    const fetchMock = stubFetch({ '/api/profile': done, '/api/facts': FACTS, '/api/auth/me': { ...ME, user: { ...ME.user, id: 2, display_name: 'Alex' } },
      'POST /api/profile/confirm': () => reply({ ...done, me: { ...done.me, confirmed: true } }) });
    atProfile('/profile/you');
    expect(await screen.findByText(/^Saved Oct 14 by JR$/)).toBeInTheDocument();
    await waitFor(() => expect(document.querySelectorAll('.is-mine').length).toBe(2));
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }));
    await waitFor(() => expect(callsTo(fetchMock, 'POST', '/api/profile/confirm')).toHaveLength(1));
  });
});
