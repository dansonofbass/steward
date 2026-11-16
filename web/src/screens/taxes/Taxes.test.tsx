import { screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { stubFetch, wrapBook } from '../../test-utils';
import { NOT_ADVICE } from '../../ui/NotAdvice';
import Taxes from './Taxes';

afterEach(() => vi.unstubAllGlobals());

describe('The Taxes page', () => {
  it('shows the three cards in order', async () => {
    const no = { available: false, reason: 'Add both birth dates, your state and how you file taxes in Set up first.' };
    stubFetch({ '/api/taxes/quarterly': no, '/api/taxes/plans': no, '/api/taxes/roth': no });
    wrapBook(<Taxes />, {}, '/b/ours/taxes');
    expect(await screen.findByRole('heading', { name: 'Taxes', level: 1 })).toBeInTheDocument();
    await waitFor(() => expect(screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent))
      .toEqual(['Quarterly taxes', 'Solo 401(k) or SEP', 'Roth or traditional']));
  });

  it('ends with the not-advice line', async () => {
    const no = { available: false, reason: 'Add both birth dates, your state and how you file taxes in Set up first.' };
    stubFetch({ '/api/taxes/quarterly': no, '/api/taxes/plans': no, '/api/taxes/roth': no });
    wrapBook(<Taxes />, {}, '/b/ours/taxes');
    expect(await screen.findByText(NOT_ADVICE)).toBeInTheDocument();
  });

  it('sits in the Plan row with Taxes on; while setup is unfinished the row is Overview and Taxes', async () => {
    const no = { available: false, reason: 'Add both birth dates, your state and how you file taxes in Set up first.' };
    const names = { jr: 'JR', spouse: 'Sam', joint: 'Joint' };
    const taxes = { '/api/taxes/quarterly': no, '/api/taxes/plans': no, '/api/taxes/roth': no };
    const linksOf = () => within(screen.getByRole('navigation', { name: 'Plan pages' })).getAllByRole('link');
    stubFetch({ ...taxes, '/api/plan/setup': { ready: true, setup: [], names } });
    const { unmount } = wrapBook(<Taxes />, {}, '/b/ours/taxes');
    expect(linksOf().map((a) => a.textContent)).toEqual(['Overview', 'Try changes', 'Next dollar', 'How it works', 'Taxes']);
    expect(linksOf().at(-1)).toHaveAttribute('aria-current', 'page');
    unmount();
    stubFetch({ ...taxes, '/api/plan/setup': { ready: false, setup: [], names } });
    wrapBook(<Taxes />, {}, '/b/ours/taxes');
    await waitFor(() => expect(linksOf().map((a) => a.textContent)).toEqual(['Overview', 'Taxes']));
  });
});
