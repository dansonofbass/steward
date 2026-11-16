import { screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { stubFetch, wrapBook } from '../../test-utils';
import { FlagsBlock } from './FlagsBlock';
import { LIST, PARENT } from './fixtures';

afterEach(() => vi.unstubAllGlobals());

describe("Home's Look into block", () => {
  it('reads like the mockup: count, urgent, when it ran, five rows and what is left', async () => {
    stubFetch({ '/api/flags': LIST });
    wrapBook(<FlagsBlock />, PARENT, '/b/margaret-ellis');
    const block = await screen.findByRole('region', { name: 'Look into' });
    expect(within(block).getByRole('heading', { name: /Look into/ })).toHaveTextContent('Look into 6');
    expect(within(block).getByText('3 urgent')).toBeInTheDocument();
    expect(within(block).getByText('Checked today, 6:12 AM')).toBeInTheDocument();
    expect(within(block).getAllByTestId('flag-row')).toHaveLength(5);
    expect(within(block).getByText('1 more: Duplicate: $64.18 at Ralphs, twice, Still checking (JR)')).toBeInTheDocument();
    expect(within(block).getByRole('link', { name: /See all 6/ })).toHaveAttribute('href', '/b/margaret-ellis/look-into');
  });
  it('is one line when nothing is open', async () => {
    stubFetch({ '/api/flags': { ...LIST, flags: [], counts: { open: 0, done: 3 } } });
    wrapBook(<FlagsBlock />, PARENT, '/b/margaret-ellis');
    expect(await screen.findByText('Nothing to look into')).toBeInTheDocument();
    expect(screen.getByText('· checked today, 6:12 AM, after the bank feed sync')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Done flags/ })).toHaveAttribute('href', '/b/margaret-ellis/look-into?show=done');
  });
  it("tells managers when email isn't set up, and not viewers", async () => {
    stubFetch({ '/api/flags': { ...LIST, mail_ready: false } });
    const { unmount } = wrapBook(<FlagsBlock />, PARENT, '/b/margaret-ellis');
    expect(await screen.findByText(/Email isn't set up, so nobody is emailed about these./)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Settings' })).toHaveAttribute('href', '/b/margaret-ellis/settings/watching');
    unmount();
    stubFetch({ '/api/flags': { ...LIST, mail_ready: null, can_edit: false } });
    wrapBook(<FlagsBlock />, { ...PARENT, role: 'viewer' }, '/b/margaret-ellis');
    expect(await screen.findByText('3 urgent')).toBeInTheDocument();
    expect(screen.queryByText(/Email isn't set up/)).toBeNull();
  });
});
