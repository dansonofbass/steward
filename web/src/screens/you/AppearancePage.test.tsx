import { fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { BOOK, callsTo, renderAt, reply, stubFetch, wrap } from '../../test-utils';
import AppearancePage from './AppearancePage';

describe('Appearance', () => {
  it('is a page of its own with the three choices', () => {
    wrap(<AppearancePage />);
    expect(screen.getByRole('heading', { level: 1, name: 'Appearance' })).toBeInTheDocument();
    const dark = screen.getByRole('radio', { name: 'Dark' });
    fireEvent.click(dark);
    expect(dark).toBeChecked();
  });
});

describe('Appearance: Celebrations and Sound (sorting redesign, Settings)', () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => vi.unstubAllGlobals());

  it('Celebrations is on and Sound off by default, each saved for the person', async () => {
    const fetchMock = stubFetch({ 'PATCH /api/auth/me': { user: { id: 1, username: 'jr', display_name: 'JR', prefs: { celebrations: null, sound: true } } } });
    wrap(<AppearancePage />);
    const cel = screen.getByRole('switch', { name: 'Celebrations' });
    const sound = screen.getByRole('switch', { name: 'Sound' });
    expect(cel).toBeChecked();
    expect(sound).not.toBeChecked();
    fireEvent.click(sound);
    await waitFor(() => expect(callsTo(fetchMock, 'PATCH', '/api/auth/me').map((c) => c.body)).toEqual([{ sound: true }]));
    fireEvent.click(cel);
    await waitFor(() => expect(callsTo(fetchMock, 'PATCH', '/api/auth/me').map((c) => c.body)).toEqual([{ sound: true }, { celebrations: false }]));
    expect(sound).toBeDisabled();
    expect(localStorage.getItem('steward-celebrations')).toBeNull();          // nothing per device any more
  });

  it('a refused save puts the switch back and says why', async () => {
    stubFetch({ 'PATCH /api/auth/me': () => reply({ error: "Steward couldn't save that." }, 500) });
    wrap(<AppearancePage />);
    const sound = screen.getByRole('switch', { name: 'Sound' });
    fireEvent.click(sound);
    expect(await screen.findByText("Steward couldn't save that.")).toBeInTheDocument();
    expect(sound).not.toBeChecked();
  });

  it('shows Celebrations off, with the reason, on a device set to reduce motion', () => {
    vi.stubGlobal('matchMedia', (q: string) => ({ matches: q.includes('reduce'), media: q, addEventListener: () => {}, removeEventListener: () => {} }));
    wrap(<AppearancePage />);
    const cel = screen.getByRole('switch', { name: 'Celebrations' });
    expect(cel).not.toBeChecked();
    expect(cel).toBeDisabled();
    expect(cel).toHaveAccessibleDescription('Off while this device is set to reduce motion');
  });
});

describe('Appearance: Swipe to sort (review focus P2)', () => {
  beforeEach(() => localStorage.clear());

  it('is on by default and kept for this device; Replay is disabled while it is off', () => {
    wrap(<AppearancePage />);
    const swipe = screen.getByRole('switch', { name: 'Swipe to sort' });
    expect(swipe).toBeChecked();
    fireEvent.click(swipe);
    expect(localStorage.getItem('steward-swipe')).toBe('off');
    expect(screen.getByRole('button', { name: 'Replay the swipe demo' })).toBeDisabled();
  });

  it('Replay the swipe demo clears the demo and opens Review in focus', () => {
    localStorage.setItem('steward-swipe-demo', 'done');
    localStorage.setItem('steward-review-view:1', 'list');
    const { location } = renderAt(<AppearancePage />, {}, '/you/appearance', [BOOK]);
    fireEvent.click(screen.getByRole('button', { name: 'Replay the swipe demo' }));
    expect(localStorage.getItem('steward-swipe-demo')).toBeNull();
    expect(localStorage.getItem('steward-review-view:1')).toBe('focus');
    expect(location.current.pathname).toBe('/b/ours/review');
  });
});
