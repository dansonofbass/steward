import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { LabelView, Txn } from '../../api/types';
import { callsTo, renderAt, reply, stubFetch } from '../../test-utils';
import { Sheet } from '../../ui/Sheet';
import NoteForm, { alsoLabel } from './NoteForm';

afterEach(() => vi.unstubAllGlobals());
const TXN = { id: 7, merchant: 'PayPal', raw_description: 'PAYPAL *DISNEYPLUS', amount_cents: -1399 } as Txn;
const VIEW: LabelView = { nickname: null, reach: { others: 11, payee: 'PayPal', amount_cents: -1399, generic: true }, rule: null };
const loaded = () => waitFor(() => expect(screen.getByTestId('note-form')).not.toHaveAttribute('aria-busy', 'true'));

describe('"Also…" (copy table)', () => {
  it('names the payee, and the amount for a generic one, and the one other', () => {
    expect(alsoLabel(VIEW)).toBe('Also the 11 PayPal $13.99 ones');
    expect(alsoLabel({ ...VIEW, reach: { ...VIEW.reach!, others: 1 } })).toBe('Also the other PayPal $13.99 one');
    expect(alsoLabel({ ...VIEW, reach: { others: 3, payee: 'StreamBox', amount_cents: null, generic: false } })).toBe('Also the 3 StreamBox ones');
    expect(alsoLabel({ ...VIEW, reach: { others: 1, payee: 'StreamBox', amount_cents: null, generic: false } })).toBe('Also the other StreamBox one');
    expect(alsoLabel({ ...VIEW, reach: { ...VIEW.reach!, others: 0 } })).toBeNull();
    expect(alsoLabel({ ...VIEW, reach: null })).toBeNull();
  });
});

describe('the note form in a sheet (16i review I-2)', () => {
  it('after a saved name, Close asks nothing about the name the form now shows', async () => {
    let named = false;
    stubFetch({
      '/api/transactions/7/label': () => reply(named ? { ...VIEW, nickname: 'Disney+' } : VIEW),
      'PUT /api/transactions/7/label': () => { named = true; return reply({ rows: 1, notes_added: 0, named: 1, rule_id: null, undo: 'tok-n' }); },
      '/api/transactions/7/notes': { notes: [] },
    });
    const onClose = vi.fn();
    renderAt(<Sheet open onClose={onClose} title="PayPal"><NoteForm txn={TXN} /></Sheet>, {}, '/transactions');
    await loaded();
    const name = screen.getByLabelText('Name');
    name.focus();
    fireEvent.change(name, { target: { value: 'Disney+' } });
    fireEvent.click(screen.getByLabelText('Also the 11 PayPal $13.99 ones'));
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(screen.getByTestId('undo-toast')).toHaveTextContent(/^Saved/));
    await waitFor(() => expect(screen.getByLabelText('Name')).toHaveValue('Disney+'));
    fireEvent.click(screen.getByRole('button', { name: 'Close' }));
    expect(screen.queryByText('Discard what you typed?')).toBeNull();
    expect(onClose).toHaveBeenCalledOnce();
  });
});

describe('the note form (item 5)', () => {
  it('saves a note, a name, Also and future ones in one request, says how many, and Undo takes it back', async () => {
    const fetchMock = stubFetch({
      '/api/transactions/7/label': VIEW,
      'PUT /api/transactions/7/label': { rows: 12, notes_added: 12, named: 12, rule_id: 4, undo: 'tok-l' },
      'POST /api/undo/tok-l': { undone: 0, transaction: null },
    });
    renderAt(<NoteForm txn={TXN} />, {}, '/transactions');
    fireEvent.change(await screen.findByLabelText('Note'), { target: { value: 'Disney+ subscription' } });
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Disney+' } });
    expect(screen.getByLabelText('Name')).not.toHaveAttribute('placeholder');      // the label says it (lean copy)
    expect(await screen.findByLabelText('Also the 11 PayPal $13.99 ones')).toBeChecked();
    const future = screen.getByLabelText('And future ones');
    expect(future).not.toBeChecked();
    fireEvent.click(future);
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(await screen.findByRole('status')).toHaveTextContent('Saved on 12 · Undo');
    expect(callsTo(fetchMock, 'PUT', '/api/transactions/7/label')[0].body).toEqual(
      { note: 'Disney+ subscription', nickname: 'Disney+', also: true, future: true });
    expect(screen.getByLabelText('Note')).toHaveValue('');
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Undo' })); });
    expect(callsTo(fetchMock, 'POST', '/api/undo/tok-l')).toHaveLength(1);
  });

  it("prefills the rule's name, starts future ticked when a rule carries a label, and unticking sends future off", async () => {
    const fetchMock = stubFetch({
      '/api/transactions/7/label': { ...VIEW, rule: { id: 4, nickname: 'Disney+', note: null, has_category: false } },
      'PUT /api/transactions/7/label': { rows: 1, notes_added: 1, named: 0, rule_id: 4, undo: 'tok-m' },
    });
    renderAt(<NoteForm txn={TXN} />, {}, '/transactions');
    await waitFor(() => expect(screen.getByLabelText('Name')).toHaveValue('Disney+'));
    const future = screen.getByLabelText('And future ones');
    expect(future).toBeChecked();
    expect(future).not.toBeDisabled();
    fireEvent.click(future);
    fireEvent.click(screen.getByLabelText('Also the 11 PayPal $13.99 ones'));
    fireEvent.change(screen.getByLabelText('Note'), { target: { value: 'renewed' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(await screen.findByRole('status')).toHaveTextContent('Saved · Undo');
    expect(callsTo(fetchMock, 'PUT', '/api/transactions/7/label')[0].body).toEqual({ note: 'renewed', nickname: 'Disney+', also: false, future: false });
  });

  it('a note alone starts Also unticked, so it stays on its own row; Also is still one tap', async () => {
    const fetchMock = stubFetch({
      '/api/transactions/7/label': VIEW,
      'PUT /api/transactions/7/label': { rows: 1, notes_added: 1, named: 0, rule_id: null, undo: 'tok-n' },
    });
    renderAt(<NoteForm txn={TXN} />, {}, '/transactions');
    const also = await screen.findByLabelText('Also the 11 PayPal $13.99 ones');
    expect(also).not.toBeChecked();
    fireEvent.change(screen.getByLabelText('Note'), { target: { value: 'Asked Sam about this one' } });
    expect(also).not.toBeChecked();
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(await screen.findByRole('status')).toHaveTextContent('Saved · Undo');
    expect(callsTo(fetchMock, 'PUT', '/api/transactions/7/label')[0].body).toEqual(
      { note: 'Asked Sam about this one', nickname: null, also: false, future: false });
  });

  it('typing a name ticks an untouched Also; a manual untick is kept through more typing', async () => {
    const fetchMock = stubFetch({
      '/api/transactions/7/label': VIEW,
      'PUT /api/transactions/7/label': { rows: 1, notes_added: 0, named: 1, rule_id: null, undo: 'tok-o' },
    });
    renderAt(<NoteForm txn={TXN} />, {}, '/transactions');
    const also = await screen.findByLabelText('Also the 11 PayPal $13.99 ones');
    const name = screen.getByLabelText('Name');
    fireEvent.change(name, { target: { value: 'D' } });
    expect(also).toBeChecked();
    fireEvent.change(name, { target: { value: '' } });
    expect(also).not.toBeChecked();
    fireEvent.change(name, { target: { value: 'Disney' } });
    expect(also).toBeChecked();
    fireEvent.click(also);
    expect(also).not.toBeChecked();
    fireEvent.change(name, { target: { value: 'Disney+' } });
    expect(also).not.toBeChecked();
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(await screen.findByRole('status')).toHaveTextContent('Saved · Undo');
    expect(callsTo(fetchMock, 'PUT', '/api/transactions/7/label')[0].body).toEqual({ note: null, nickname: 'Disney+', also: false, future: false });
    expect(also).not.toBeChecked();                                     // cleared form: no name, so back to unticked
  });

  it('asks for a note or a name, and shows the server words', async () => {
    const fetchMock = stubFetch({ '/api/transactions/7/label': VIEW, 'PUT /api/transactions/7/label': () => reply({ error: "That's more than 500 rows. Narrow it with the amount." }, 422) });
    renderAt(<NoteForm txn={TXN} />, {}, '/transactions');
    fireEvent.click(await screen.findByRole('button', { name: 'Save' }));
    expect(screen.getByRole('alert')).toHaveTextContent('Add a note or a name.');
    expect(callsTo(fetchMock, 'PUT', '/api/transactions/7/label')).toHaveLength(0);
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Disney+' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(await screen.findByRole('alert')).toHaveTextContent("That's more than 500 rows. Narrow it with the amount.");
  });

  it('a description no rule can be made from offers neither Also nor future ones; Cancel and Escape close', async () => {
    const onCancel = vi.fn();
    stubFetch({ '/api/transactions/7/label': { nickname: null, reach: null, rule: null } });
    renderAt(<NoteForm txn={TXN} onCancel={onCancel} />, {}, '/transactions');
    await screen.findByLabelText('Note');
    await loaded();
    expect(screen.queryByLabelText('And future ones')).toBeNull();
    expect(screen.queryByLabelText(/^Also/)).toBeNull();
    fireEvent.keyDown(screen.getByLabelText('Note'), { key: 'Escape' });
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(onCancel).toHaveBeenCalledTimes(2);
  });

  it('Enter saves from Note or Name; Shift+Enter is a new line (review focus P27, everywhere the form is used)', async () => {
    const fetchMock = stubFetch({ '/api/transactions/7/label': VIEW,
      'PUT /api/transactions/7/label': { rows: 1, notes_added: 1, named: 0, rule_id: null, undo: 'tok-l' } });
    renderAt(<NoteForm txn={TXN} />, {}, '/transactions');
    const note = await screen.findByLabelText('Note');
    await loaded();
    fireEvent.change(note, { target: { value: 'line one' } });
    fireEvent.keyDown(note, { key: 'Enter', shiftKey: true });
    expect(callsTo(fetchMock, 'PUT', '/api/transactions/7/label')).toHaveLength(0);
    fireEvent.keyDown(note, { key: 'Enter' });
    await waitFor(() => expect(callsTo(fetchMock, 'PUT', '/api/transactions/7/label')).toHaveLength(1));
    expect(await screen.findByRole('status')).toHaveTextContent('Saved · Undo');
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Disney+' } });
    fireEvent.keyDown(screen.getByLabelText('Name'), { key: 'Enter' });
    await waitFor(() => expect(callsTo(fetchMock, 'PUT', '/api/transactions/7/label')).toHaveLength(2));
  });

  it('with onSaved it hands back the token and its words instead of its own toast; autoFocus puts focus in Note', async () => {
    stubFetch({ '/api/transactions/7/label': VIEW,
      'PUT /api/transactions/7/label': { rows: 12, notes_added: 12, named: 0, rule_id: null, undo: 'tok-l' } });
    const onSaved = vi.fn();
    renderAt(<NoteForm txn={TXN} autoFocus onSaved={onSaved} />, {}, '/transactions');
    const note = await screen.findByLabelText('Note');
    expect(document.activeElement).toBe(note);
    await loaded();
    fireEvent.change(note, { target: { value: 'Asked Sam' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith({ token: 'tok-l', text: 'Saved on 12' }));
    expect(screen.queryByRole('status')).toBeNull();
  });
});
