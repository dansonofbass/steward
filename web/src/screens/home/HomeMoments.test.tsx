import { screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { callsTo, stubFetch, wrapBook } from '../../test-utils';
import { HomeTree, newGrowthLine, ProfileGrowth, progressLine } from './HomeMoments';

const fx = vi.hoisted(() => ({ acorn: vi.fn(() => () => {}), winMoment: vi.fn(() => () => {}) }));
vi.mock('../../celebrate/celebrate', () => fx);
afterEach(() => { vi.clearAllMocks(); vi.unstubAllGlobals(); });

const KEYS = ['first_month', 'covered', 'checklist', 'year', 'five_years'] as const;
const growth = (stage: number, met: boolean[], seen: boolean) => ({ stage, seen, milestones: KEYS.map((key, i) => ({ key, met: met[i] })) });

describe('the growth tree (phase 17 spec 3.4)', () => {
  it('names the completed month on Home (issue #33)', async () => {
    const g = growth(1, [true, false, false, false, false], false);
    stubFetch({ '/api/growth': { ...g, milestones: [{ ...g.milestones[0], month: '2026-09' }, ...g.milestones.slice(1)] },
      'POST /api/growth/seen': () => new Response(null, { status: 204 }) });
    wrapBook(<HomeTree />);
    expect(await screen.findByRole('status')).toHaveTextContent('New growth: September 2026 is fully sorted.');
  });

  it('keeps December in its own year and falls back safely for older APIs', () => {
    const g = growth(1, [true, false, false, false, false], false);
    expect(newGrowthLine({ ...g, milestones: [{ ...g.milestones[0], month: '2026-12' }, ...g.milestones.slice(1)] }))
      .toBe('New growth: December 2026 is fully sorted.');
    expect(newGrowthLine(g)).toBe('New growth: a past month fully sorted.');
  });

  it('a new stage hops once on Home, says which milestone, and marks it seen', async () => {
    const fetchMock = stubFetch({ '/api/growth': growth(3, [true, false, true, true, false], false), 'POST /api/growth/seen': () => new Response(null, { status: 204 }) });
    wrapBook(<HomeTree />);
    expect(await screen.findByRole('status')).toHaveTextContent('New growth: a year of history.');
    expect(document.querySelector('svg.oak')).toHaveAttribute('data-stage', '3');
    await waitFor(() => expect(callsTo(fetchMock, 'POST', '/api/growth/seen').map((c) => c.body)).toEqual([{ stage: 3 }]));
    await waitFor(() => expect(fx.acorn).toHaveBeenCalledWith(expect.objectContaining({ motion: 'hop' })));
  });

  it('a stage already seen sits still and says nothing', async () => {
    const fetchMock = stubFetch({ '/api/growth': growth(3, [true, false, true, true, false], true) });
    wrapBook(<HomeTree />);
    await screen.findByTestId('home-tree');
    expect(screen.queryByRole('status')).toBeNull();
    expect(callsTo(fetchMock, 'POST', '/api/growth/seen')).toEqual([]);
    expect(fx.acorn).not.toHaveBeenCalled();
  });

  it('stage 0 is the resting acorn', async () => {
    stubFetch({ '/api/growth': growth(0, [false, false, false, false, false], true) });
    wrapBook(<HomeTree />);
    expect((await screen.findByTestId('home-tree')).querySelector('svg.acorn')).toHaveAttribute('data-face', 'resting');
  });

  it('under reduced motion the new stage still shows and says its line, with no motion asked for', async () => {
    vi.stubGlobal('matchMedia', (q: string) => ({ matches: q.includes('reduce'), media: q, addEventListener: () => {}, removeEventListener: () => {} }));
    stubFetch({ '/api/growth': growth(1, [false, false, false, true, false], false), 'POST /api/growth/seen': () => new Response(null, { status: 204 }) });
    wrapBook(<HomeTree />);
    expect(await screen.findByRole('status')).toHaveTextContent('New growth: a year of history.');
    expect(document.querySelector('svg.oak')).not.toBeNull();
    expect(fx.acorn).not.toHaveBeenCalled();
  });

  it('a parent book has no tree and never asks for one', async () => {
    const fetchMock = stubFetch({});
    wrapBook(<HomeTree />, { kind: 'parent' });
    await Promise.resolve();
    expect(document.querySelector('[data-testid=home-tree]')).toBeNull();
    expect(callsTo(fetchMock, 'GET', '/api/growth')).toEqual([]);
  });

  it('Profile lists the milestones and what comes next', async () => {
    stubFetch({ '/api/growth': growth(3, [true, false, true, true, false], true) });
    wrapBook(<ProfileGrowth />);
    expect(await screen.findByText("3 of 5: the first set-aside covered before it's due comes next")).toBeInTheDocument();
    expect(screen.getAllByRole('listitem')).toHaveLength(5);
  });

  it("Profile's milestones say reached or not in words, not by the hidden icon alone (THO-11)", async () => {
    stubFetch({ '/api/growth': growth(3, [true, false, true, true, false], true) });
    wrapBook(<ProfileGrowth />);
    await screen.findByTestId('profile-growth');
    const said = screen.getAllByRole('listitem').map((li) => li.textContent ?? '');
    expect(said.map((t) => /, reached$/.test(t))).toEqual([true, false, true, true, false]);
    expect(said.map((t) => /, not yet$/.test(t))).toEqual([false, true, false, false, true]);
  });

  it('the lines: the newest milestone met, and a full-grown oak', () => {
    expect(newGrowthLine(growth(1, [false, false, false, true, false], false))).toBe('New growth: a year of history.');
    expect(newGrowthLine(growth(2, [false, false, false, false, false], false))).toBe('New growth.');
    expect(progressLine(growth(5, [true, true, true, true, true], true))).toBe('5 of 5. A full-grown oak.');
  });
});
