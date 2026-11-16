import { render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { PlanReady } from './api';
import { ChangeLine } from './ChangeLine';
import { CLOSER_CHEERS } from './copy';
import { planFixture } from './fixtures';

const loaded = vi.hoisted(() => vi.fn());
vi.mock('../../celebrate/celebrate', () => {
  loaded();
  return { closer: vi.fn(), acorn: vi.fn(() => () => {}), winMoment: vi.fn(() => () => {}) };
});

beforeEach(() => localStorage.clear());
afterEach(() => vi.unstubAllGlobals());

/** The fixture with today's Comfortably age `months` earlier than the saved plan's. */
function moved(months: number): PlanReady {
  const d = planFixture();
  d.inputs_summary.comfortable_months = d.plan!.inputs_summary!.comfortable_months! - months;
  return d;
}

describe('with celebrations off, the cheer is still said and nothing loads or moves (plan subpages decision 7)', () => {
  it('on a device set to reduce motion', async () => {
    vi.stubGlobal('matchMedia', (q: string) => ({ matches: q.includes('reduce'), media: q, addEventListener: () => {}, removeEventListener: () => {} }));
    render(<ChangeLine data={moved(12)} />);
    expect(CLOSER_CHEERS.year).toContain(screen.getByTestId('change-cheer').textContent);
    await new Promise((r) => setTimeout(r, 0));
    expect(loaded).not.toHaveBeenCalled();
  });

  it('switched off in Appearance', async () => {
    localStorage.setItem('steward-celebrations', 'off');
    render(<ChangeLine data={moved(12)} />);
    expect(CLOSER_CHEERS.year).toContain(screen.getByTestId('change-cheer').textContent);
    await new Promise((r) => setTimeout(r, 0));
    expect(loaded).not.toHaveBeenCalled();
  });
});
