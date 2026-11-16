import { screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { BOOK, callsTo, renderAt, stubFetch } from '../../test-utils';
import Help from './Help';

afterEach(() => vi.unstubAllGlobals());

describe('Help (guided setup spec 7.5)', () => {
  it("replays this book's welcome without marking it", async () => {
    const fetchMock = stubFetch({});
    renderAt(<Help />, {}, '/you/help', [BOOK]);
    expect(screen.getByRole('heading', { level: 1, name: 'Help' })).toBeInTheDocument();
    expect(await screen.findByRole('link', { name: 'See the welcome again' })).toHaveAttribute('href', '/b/ours/welcome?again=1');
    expect(callsTo(fetchMock, 'POST', '/api')).toEqual([]);
  });

  it('offers Get Steward ready to an install manager only', async () => {
    stubFetch({});
    const a = renderAt(<Help />, {}, '/you/help', [{ ...BOOK, install: true }]);
    expect(await screen.findByRole('link', { name: 'Get Steward ready' })).toHaveAttribute('href', '/b/ours/settings/ready');
    a.unmount();
    renderAt(<Help />, {}, '/you/help', [{ ...BOOK, install: false }]);
    expect(await screen.findByRole('link', { name: 'See the welcome again' })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Get Steward ready' })).toBeNull();
  });

  it('offers no welcome in a Sample', async () => {
    stubFetch({});
    renderAt(<Help />, { sample: true }, '/you/help', [{ ...BOOK, sample: true, install: true }]);
    expect(await screen.findByRole('link', { name: 'Get Steward ready' })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'See the welcome again' })).toBeNull();
  });
});
