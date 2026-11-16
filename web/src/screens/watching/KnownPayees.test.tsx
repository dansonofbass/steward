import { fireEvent, screen, within } from '@testing-library/react';
import { Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { callsTo, expectRemovalSaid, reply, stubFetch, wrapBook } from '../../test-utils';
import { PARENT, SETTINGS } from './fixtures';
import { Watching } from './Watching';

afterEach(() => vi.unstubAllGlobals());

describe('Known payees', () => {
  it('lists them with what they quiet, and removes one with a note', async () => {
    let current = SETTINGS;
    const fetchMock = stubFetch({ '/api/watching': () => reply(current),
      'POST /api/watching/known/4/remove': () => { current = { ...SETTINGS, known: [] }; return reply(current); } });
    wrapBook(<Routes><Route path="/b/:slug/settings/:section/:step" element={<Watching />} /></Routes>, PARENT, '/b/margaret-ellis/settings/watching/known');
    expect(await screen.findByRole('heading', { name: /Known payees/ })).toBeInTheDocument();
    expect(screen.getByText(/Scam patterns, duplicates, missed money and low balances are always flagged./)).toBeInTheDocument();
    expect(screen.getByText('Brea Family Dental')).toBeInTheDocument();
    expect(screen.getByText('$480 to $800')).toBeInTheDocument();
    expect(screen.getByText('Robin, Oct 9, from a Large amount flag · "Margaret\'s crown."')).toBeInTheDocument();
    const button = screen.getByRole('button', { name: 'Remove Brea Family Dental' });
    button.focus();
    fireEvent.click(button);
    const sheet = await screen.findByRole('dialog', { name: 'Remove Brea Family Dental?' });
    fireEvent.change(within(sheet).getByLabelText('Why (optional)'), { target: { value: 'The crown is done.' } });
    fireEvent.click(within(sheet).getByRole('button', { name: 'Remove' }));
    await vi.waitFor(() => expect(callsTo(fetchMock, 'POST', '/api/watching/known/4/remove')[0]?.body).toEqual({ note: 'The crown is done.' }));
    expect(await screen.findByText('No known payees yet. Marking a flag Expected can add one.')).toBeInTheDocument();
    // THO-1: the removal is said, and focus is on the heading, not on <body> where the gone row's button left it.
    await expectRemovalSaid('Removed Brea Family Dental.', () => screen.getByRole('heading', { name: /Known payees/ }));
  });
  it('does not carry a failed removal\'s error into the next time the sheet opens', async () => {
    stubFetch({ '/api/watching': SETTINGS, 'POST /api/watching/known/4/remove': () => reply({ error: 'Could not remove it.' }, 500) });
    wrapBook(<Routes><Route path="/b/:slug/settings/:section/:step" element={<Watching />} /></Routes>, PARENT, '/b/margaret-ellis/settings/watching/known');
    fireEvent.click(await screen.findByRole('button', { name: 'Remove Brea Family Dental' }));
    let sheet = await screen.findByRole('dialog', { name: 'Remove Brea Family Dental?' });
    fireEvent.click(within(sheet).getByRole('button', { name: 'Remove' }));
    expect(await within(sheet).findByText('Could not remove it.')).toBeInTheDocument();
    fireEvent.click(within(sheet).getByRole('button', { name: 'Keep it' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Remove Brea Family Dental' }));
    sheet = await screen.findByRole('dialog', { name: 'Remove Brea Family Dental?' });
    expect(within(sheet).queryByText('Could not remove it.')).toBeNull();
  });
});
