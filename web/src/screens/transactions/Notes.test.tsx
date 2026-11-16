import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { BookSummary, Me, Txn } from '../../api/types';
import { letTestingLibraryDriveFakeTimers, useFakeTimers } from '../../test-clock';
import { callsTo, reply, renderAt, stubFetch } from '../../test-utils';
import { Notes } from './Notes';

afterEach(() => vi.unstubAllGlobals());

const TXN = { id: 7 } as Txn;
const NOTES = { notes: [
  { id: 1, author_id: 1, author_name: 'JR', body: 'Water heater, half paid by Sam', created_at: '2026-10-11T18:00:00+00:00' },
  { id: 2, author_id: 2, author_name: 'Sam', body: 'Paid my half', created_at: '2026-10-12T18:00:00+00:00' },
] };
const ME: Me = { user: { id: 1, username: 'jr', display_name: 'JR', email: null }, books: [], session: { id: 1, device_label: 'Laptop', created_at: '2026-10-01T00:00:00Z' } };
const open = (book: Partial<BookSummary> = {}) => {
  const r = renderAt(<Notes txn={TXN} today={new Date(2026, 9, 13)} />, book, '/transactions');
  r.qc.setQueryData(['me'], ME);
  return r;
};

describe('Notes on a transaction (phase 12 decision 18)', () => {
  it('lists who wrote what and when, newest last, with Remove on your own only', async () => {
    stubFetch({ '/api/transactions/7/notes': NOTES });
    open();
    expect(await screen.findByText('JR, Oct 11:')).toBeInTheDocument();
    const items = screen.getAllByRole('listitem');
    expect(items.map((li) => li.textContent)).toEqual(['JR, Oct 11: Water heater, half paid by SamRemove', 'Sam, Oct 12: Paid my half']);
  });
  it('adds a note and clears the box', async () => {
    const fetchMock = stubFetch({ '/api/transactions/7/notes': NOTES, 'POST /api/transactions/7/notes': () => reply({ id: 3, author_id: 1, author_name: 'JR', body: 'Third', created_at: '2026-10-13T18:00:00+00:00' }, 201) });
    open({ kind: 'parent' });
    fireEvent.change(await screen.findByLabelText('Note'), { target: { value: '  Third  ' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add note' }));
    await waitFor(() => expect(callsTo(fetchMock, 'POST', '/api/transactions/7/notes')[0].body).toEqual({ body: 'Third' }));
    await waitFor(() => expect(screen.getByLabelText('Note')).toHaveValue(''));
  });
  it("adding or removing a note tells Review to reload its counts, so the card shows the change at once", async () => {
    const fetchMock = stubFetch({ '/api/transactions/7/notes': NOTES,
      'POST /api/transactions/7/notes': () => reply({ id: 3, author_id: 1, author_name: 'JR', body: 'Third', created_at: '2026-10-13T18:00:00+00:00' }, 201),
      'DELETE /api/transactions/7/notes/1': () => reply({ undo: 'tok-rm' }) });
    const r = open({ kind: 'parent' });
    const spy = vi.spyOn(r.qc, 'invalidateQueries');
    fireEvent.change(await screen.findByLabelText('Note'), { target: { value: 'Third' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add note' }));
    await waitFor(() => expect(spy).toHaveBeenCalledWith({ queryKey: ['review'] }));
    spy.mockClear();
    fireEvent.click(await screen.findByRole('button', { name: 'Remove note from Oct 11' }));
    await waitFor(() => expect(callsTo(fetchMock, 'DELETE', '/api/transactions/7/notes/1')).toHaveLength(1));
    await waitFor(() => expect(spy).toHaveBeenCalledWith({ queryKey: ['review'] }));
  });
  it('a household book adds through the note form', async () => {
    stubFetch({ '/api/transactions/7/notes': NOTES, '/api/transactions/7/label': { nickname: null, reach: null, rule: null } });
    open();
    expect(await screen.findByTestId('note-form')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Add note' })).toBeNull();
  });
  it('removes your own note', async () => {
    const fetchMock = stubFetch({ '/api/transactions/7/notes': NOTES, 'DELETE /api/transactions/7/notes/1': () => reply({ undo: 'tok-rm' }) });
    open();
    fireEvent.click(await screen.findByRole('button', { name: 'Remove note from Oct 11' }));
    await waitFor(() => expect(callsTo(fetchMock, 'DELETE', '/api/transactions/7/notes/1')).toHaveLength(1));
  });
  it('shows a viewer the notes and no add box', async () => {
    stubFetch({ '/api/transactions/7/notes': NOTES });
    open({ role: 'viewer' });
    expect(await screen.findByText('Sam, Oct 12:')).toBeInTheDocument();
    expect(screen.queryByLabelText('Note')).toBeNull();
    expect(screen.queryByRole('button', { name: /^Remove/ })).toBeNull();
  });
  it('says when there are none', async () => {
    stubFetch({ '/api/transactions/7/notes': { notes: [] } });
    open();
    expect(await screen.findByText('No notes yet.')).toBeInTheDocument();
  });
  it('shows the error when the notes cannot be loaded', async () => {
    stubFetch({ '/api/transactions/7/notes': () => reply({ error: 'The notes would not load.' }, 500) });
    open();
    expect(await screen.findByText('The notes would not load.')).toBeInTheDocument();
  });
  it('sends one DELETE however many times Remove is clicked', async () => {
    const fetchMock = stubFetch({ '/api/transactions/7/notes': NOTES, 'DELETE /api/transactions/7/notes/1': () => reply({ undo: 'tok-rm' }) });
    open();
    const b = await screen.findByRole('button', { name: 'Remove note from Oct 11' });
    fireEvent.click(b);
    fireEvent.click(b);
    await waitFor(() => expect(callsTo(fetchMock, 'DELETE', '/api/transactions/7/notes/1')).toHaveLength(1));
  });
  it('one toast: a save then a Remove shows only Removed · Undo, and its Undo brings back the removed note, not the save', async () => {
    const SAVED = { id: 3, author_id: 1, author_name: 'JR', body: 'Asked Sam', created_at: '2026-10-12T20:00:00+00:00' };
    let notes = NOTES.notes;
    const fetchMock = stubFetch({
      '/api/transactions/7/notes': () => reply({ notes }),
      '/api/transactions/7/label': { nickname: null, reach: null, rule: null },
      'PUT /api/transactions/7/label': () => { notes = [...NOTES.notes, SAVED]; return reply({ rows: 1, notes_added: 1, named: 0, rule_id: null, undo: 'tok-save' }); },
      'DELETE /api/transactions/7/notes/1': () => { notes = [NOTES.notes[1], SAVED]; return reply({ undo: 'tok-rm' }); },
      'POST /api/undo/tok-rm': () => { notes = [...NOTES.notes, SAVED]; return reply({ undone: 1, transaction: null }); },
    });
    open();
    fireEvent.change(await screen.findByLabelText('Note'), { target: { value: 'Asked Sam' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(document.querySelector('.undo-toast')).toHaveTextContent('Saved · Undo'));
    fireEvent.click(await screen.findByRole('button', { name: 'Remove note from Oct 11' }));
    await waitFor(() => expect(document.querySelector('.undo-toast')).toHaveTextContent('Removed · Undo'));
    expect(document.querySelectorAll('.undo-toast')).toHaveLength(1);              // the newer action replaced the older
    fireEvent.click(screen.getByRole('button', { name: 'Undo' }));
    await waitFor(() => expect(screen.getAllByRole('listitem').map((li) => li.textContent?.slice(0, 10)))
      .toEqual(['JR, Oct 11', 'Sam, Oct 1', 'JR, Oct 12']));
    expect(callsTo(fetchMock, 'POST', '/api/undo/tok-rm')).toHaveLength(1);
    expect(callsTo(fetchMock, 'POST', '/api/undo/tok-save')).toHaveLength(0);
  });
  it('a second Remove is a new toast, so its 10 seconds start again', async () => {
    const MORE = { id: 3, author_id: 1, author_name: 'JR', body: 'Third', created_at: '2026-10-12T20:00:00+00:00' };
    let notes = [...NOTES.notes, MORE];
    stubFetch({
      '/api/transactions/7/notes': () => reply({ notes }),
      'DELETE /api/transactions/7/notes/1': () => { notes = notes.filter((n) => n.id !== 1); return reply({ undo: 'tok-1' }); },
      'DELETE /api/transactions/7/notes/3': () => { notes = notes.filter((n) => n.id !== 3); return reply({ undo: 'tok-3' }); },
    });
    useFakeTimers();
    letTestingLibraryDriveFakeTimers();
    try {
      open({ kind: 'parent' });
      fireEvent.click(await screen.findByRole('button', { name: 'Remove note from Oct 11' }));
      const first = await screen.findByText('Removed');
      act(() => { vi.advanceTimersByTime(8_000); });
      fireEvent.click(await screen.findByRole('button', { name: 'Remove note from Oct 12' }));
      await waitFor(() => expect(screen.getByText('Removed')).not.toBe(first));    // a new mount
      act(() => { vi.advanceTimersByTime(8_000); });                                // 16 s since the first: still up
      expect(screen.getByText('Removed')).toBeInTheDocument();
      act(() => { vi.advanceTimersByTime(2_500); });
      expect(screen.queryByText('Removed')).toBeNull();
    } finally {
      delete (globalThis as { jest?: unknown }).jest;
    }
  });
  it('after Remove, focus goes to the Notes heading, not the page', async () => {
    stubFetch({ '/api/transactions/7/notes': NOTES, 'DELETE /api/transactions/7/notes/1': () => reply({ undo: 'tok-rm' }) });
    open();
    const b = await screen.findByRole('button', { name: 'Remove note from Oct 11' });
    b.focus();
    fireEvent.click(b);
    expect(document.activeElement).toBe(screen.getByRole('heading', { name: 'Notes' }));
    await screen.findByText('Removed');
  });
  it('Remove hides the line at once and says Removed · Undo; Undo brings it back in its place', async () => {
    let notes = NOTES.notes;
    let answer: (r: Response) => void = () => {};
    const fetchMock = stubFetch({
      '/api/transactions/7/notes': () => reply({ notes }),
      'DELETE /api/transactions/7/notes/1': () => new Promise<Response>((res) => { answer = res; }),
      'POST /api/undo/tok-rm': () => { notes = NOTES.notes; return reply({ undone: 1, transaction: null }); },
    });
    const r = open();
    const spy = vi.spyOn(r.qc, 'invalidateQueries');
    fireEvent.click(await screen.findByRole('button', { name: 'Remove note from Oct 11' }));
    expect(screen.queryByText('JR, Oct 11:')).toBeNull();                 // gone at once, before the reply
    notes = [NOTES.notes[1]];
    answer(reply({ undo: 'tok-rm' }));
    const toast = await waitFor(() => { const t = document.querySelector<HTMLElement>('.undo-toast'); if (!t) throw new Error('no toast'); return t; });
    expect(toast).toHaveTextContent('Removed · Undo');
    await waitFor(() => expect(screen.getAllByRole('listitem').map((li) => li.textContent)).toEqual(['Sam, Oct 12: Paid my half']));
    for (const key of ['notes', 'review', 'transactions']) expect(spy).toHaveBeenCalledWith({ queryKey: key === 'notes' ? ['notes', 7] : [key] });
    spy.mockClear();
    fireEvent.click(screen.getByRole('button', { name: 'Undo' }));
    await waitFor(() => expect(screen.getAllByRole('listitem').map((li) => li.textContent))
      .toEqual(['JR, Oct 11: Water heater, half paid by SamRemove', 'Sam, Oct 12: Paid my half']));
    expect(callsTo(fetchMock, 'POST', '/api/undo/tok-rm')).toHaveLength(1);
    expect(document.querySelector('.undo-toast')).toBeNull();
    for (const key of ['notes', 'review', 'transactions']) expect(spy).toHaveBeenCalledWith({ queryKey: key === 'notes' ? ['notes', 7] : [key] });
  });
});
