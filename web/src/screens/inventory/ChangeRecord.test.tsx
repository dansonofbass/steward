import { fireEvent, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { setHouseholdZone } from '../../lib/today';
import { stubFetch, wrapBook } from '../../test-utils';
import { ChangeRecord } from './ChangeRecord';

afterEach(() => vi.unstubAllGlobals());
const ROW = (id: string, at: string, text: string, extra = {}) => ({ id, at, who: 'Robin', icon: 'pencil', text, item: { id: 14, label: 'Homeowners' }, diffs: [], lines: [], note: null, summary: '', ...extra });
const PAGE1 = { people: [{ id: 1, name: 'JR' }, { id: 2, name: 'Robin' }], next: '2026-10-15T00:00:00+00:00', changes: [
  ROW('c3', '2026-10-17T03:51:00+00:00', 'edited {item}', { diffs: [{ label: 'Renewal date', before: 'not known', after: 'Mar 1' }], note: 'From the renewal notice in the March mail' }),
  ROW('c2', '2026-10-16T04:05:00+00:00', 'added {item}', { who: 'JR', icon: 'plus', lines: ['Document · power of attorney · Margaret · Confirmed'] }),
] };
const PAGE2 = { people: PAGE1.people, next: null, changes: [ROW('m1', '2026-10-10T02:15:00+00:00', 'invited Tess as a viewer', { who: 'JR', icon: 'users', item: null })] };

describe('Change record', () => {
  it('groups by day, shows old and new values, filters and pages', async () => {
    const fetchMock = stubFetch({
      '/api/changes?before=': PAGE2, '/api/changes?kind=files': { ...PAGE1, changes: [], next: null }, '/api/changes': PAGE1,
    });
    wrapBook(<ChangeRecord />, { slug: 'margaret-ellis', name: 'Margaret Ellis', kind: 'parent' }, '/b/margaret-ellis/settings/changes');
    expect(await screen.findByText("Every change a manager makes to Margaret Ellis, newest first. It can't be edited or deleted, and everyone in the book can see it.")).toBeInTheDocument();
    expect((await screen.findAllByRole('link', { name: 'Homeowners' })).length).toBeGreaterThan(0);
    expect(screen.getByText('not known').tagName).toBe('DEL');
    expect(screen.getByText('"From the renewal notice in the March mail"')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Show older' }));
    expect(await screen.findByText(/invited Tess as a viewer/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Kind of change'), { target: { value: 'files' } });
    await vi.waitFor(() => expect(fetchMock.mock.calls.some(([u]) => String(u).includes('kind=files'))).toBe(true));
  });
  it('links a flag row to its flag and shows a removed known payee struck through', async () => {
    stubFetch({ '/api/changes': { next: null, people: [], changes: [
      { id: 'c9', at: '2026-10-09T19:15:00+00:00', who: 'Robin', icon: 'flag', text: 'reopened {item}',
        item: { id: 33, label: 'Large amount: $640.00 to Brea Family Dental', path: '/look-into/33' },
        diffs: [{ label: 'Status', before: 'Expected', after: 'Open' },
                { label: 'Known payees', before: 'Brea Family Dental, $480 to $800', after: null }],
        lines: [], note: null, summary: 'Robin reopened Large amount: $640.00 to Brea Family Dental' }] } });
    wrapBook(<ChangeRecord />, { slug: 'margaret-ellis', name: 'Margaret Ellis', kind: 'parent' }, '/b/margaret-ellis/settings/changes');
    expect(await screen.findByRole('link', { name: 'Large amount: $640.00 to Brea Family Dental' }))
      .toHaveAttribute('href', '/b/margaret-ellis/look-into/33');
    expect(screen.getByText('Brea Family Dental, $480 to $800').tagName).toBe('DEL');
    expect(screen.getByRole('option', { name: 'Flags and watching' })).toBeInTheDocument();
  });
  it('puts the year in each day heading', async () => {
    stubFetch({ '/api/changes': { ...PAGE1, next: null, changes: [
      ROW('a', '2026-10-17T15:00:00+00:00', 'edited {item}'), ROW('b', '2025-10-17T15:00:00+00:00', 'edited {item}')] } });
    wrapBook(<ChangeRecord />, { slug: 'margaret-ellis', name: 'Margaret Ellis', kind: 'parent' }, '/b/margaret-ellis/settings/changes');
    await screen.findAllByRole('link', { name: 'Homeowners' });
    expect(screen.getByText(/Oct 17, 2026$/)).toBeInTheDocument();
    expect(screen.getByText(/Oct 17, 2025$/)).toBeInTheDocument();
  });
  it("heads each day and times each row on the household's clock, wherever the device is (#26)", async () => {
    setHouseholdZone('Pacific/Kiritimati');   // UTC+14: these two are either side of midnight at home
    stubFetch({ '/api/changes': { ...PAGE1, next: null, changes: [
      ROW('late', '2026-10-16T10:30:00+00:00', 'edited {item}'), ROW('early', '2026-10-16T09:30:00+00:00', 'edited {item}')] } });
    const { container } = wrapBook(<ChangeRecord />, { slug: 'margaret-ellis', name: 'Margaret Ellis', kind: 'parent' }, '/b/margaret-ellis/settings/changes');
    await screen.findAllByRole('link', { name: 'Homeowners' });
    expect([...container.querySelectorAll('.chg__day')].map((d) => d.textContent)).toEqual(['Sat, Oct 17, 2026', 'Fri, Oct 16, 2026']);
    expect([...container.querySelectorAll('.chg__time')].map((t) => t.textContent)).toEqual(['12:30 AM', '11:30 PM']);
  });
  it('shows a row whose time is empty or unreadable, under a blank heading, instead of failing the record', async () => {
    stubFetch({ '/api/changes': { ...PAGE1, next: null, changes: [
      ROW('ok', '2026-10-17T15:00:00+00:00', 'edited {item}'), ROW('blank', '', 'added {item}'), ROW('bad', 'not a time', 'removed {item}')] } });
    const { container } = wrapBook(<ChangeRecord />, { slug: 'margaret-ellis', name: 'Margaret Ellis', kind: 'parent' }, '/b/margaret-ellis/settings/changes');
    expect(await screen.findByText(/removed/)).toBeInTheDocument();
    expect(screen.getByText(/added/)).toBeInTheDocument();
    expect([...container.querySelectorAll('.chg__day')].map((d) => d.textContent)).toEqual(['Sat, Oct 17, 2026', '']);
  });
  it('keeps the person choices while a filtered list is loading', async () => {
    stubFetch({ '/api/changes?kind=files': () => new Promise(() => {}), '/api/changes': PAGE1 });
    wrapBook(<ChangeRecord />, { slug: 'margaret-ellis', name: 'Margaret Ellis', kind: 'parent' }, '/b/margaret-ellis/settings/changes');
    await screen.findAllByRole('link', { name: 'Homeowners' });
    expect(screen.getByRole('option', { name: 'Robin' })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Kind of change'), { target: { value: 'files' } });
    await vi.waitFor(() => expect(screen.getByLabelText('Kind of change')).toHaveValue('files'));
    expect(screen.getByRole('option', { name: 'Robin' })).toBeInTheDocument();
  });
});
