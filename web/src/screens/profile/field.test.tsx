import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { callsTo, reply, stubFetch } from '../../test-utils';
import { FieldCtx, ProfileField } from './field';

afterEach(() => vi.unstubAllGlobals());

function card(canEdit = true, save = vi.fn(async () => 'tok')) {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <FieldCtx.Provider value={{ mode: 'card', register: () => () => {}, canEdit }}>
        <ProfileField label="State" input="text" text="CA" shown="California" check={(t) => (t ? null : 'Choose a state.')} save={save} />
      </FieldCtx.Provider>
    </QueryClientProvider>,
  );
  return save;
}

describe('a card field', () => {
  it('the pencil opens it in place; Enter saves and shows Saved · Undo; Undo posts the token', async () => {
    const fetchMock = stubFetch({ 'POST /api/undo/tok': () => reply({ undone: 1, transaction: null }) });
    const save = card();
    expect(screen.getByText('California')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Edit State' }));
    const input = screen.getByLabelText('State');
    await waitFor(() => expect(input).toHaveFocus());
    fireEvent.change(input, { target: { value: 'OR' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(await screen.findByRole('status')).toHaveTextContent('Saved · Undo');
    expect(save).toHaveBeenCalledWith('OR');
    fireEvent.click(screen.getByRole('button', { name: 'Undo' }));
    await waitFor(() => expect(callsTo(fetchMock, 'POST', '/api/undo/tok')).toHaveLength(1));
  });

  it('Escape cancels without saving, even with a valid value typed', async () => {
    const save = card();
    fireEvent.click(screen.getByRole('button', { name: 'Edit State' }));
    const input = screen.getByLabelText('State');
    fireEvent.change(input, { target: { value: 'OR' } });
    fireEvent.keyDown(input, { key: 'Escape' });
    fireEvent.blur(input);
    expect(screen.getByText('California')).toBeInTheDocument();
    expect(save).not.toHaveBeenCalled();
  });

  it('an empty value is refused in words', async () => {
    const save = card();
    fireEvent.click(screen.getByRole('button', { name: 'Edit State' }));
    fireEvent.change(screen.getByLabelText('State'), { target: { value: '' } });
    fireEvent.keyDown(screen.getByLabelText('State'), { key: 'Enter' });
    expect(await screen.findByText('Choose a state.')).toBeInTheDocument();
    expect(save).not.toHaveBeenCalled();
  });

  it('a radios field takes focus on open, survives arrowing between radios, and Enter saves once', async () => {
    const save = vi.fn(async () => 'tok');
    render(
      <QueryClientProvider client={new QueryClient()}>
        <FieldCtx.Provider value={{ mode: 'card', register: () => () => {}, canEdit: true }}>
          <ProfileField label="Filing" input="radios" text="single" shown="Single" check={(t) => (t ? null : 'Choose one.')} save={save}
            options={[{ value: 'single', label: 'Single' }, { value: 'married', label: 'Married' }]} />
        </FieldCtx.Provider>
      </QueryClientProvider>,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Edit Filing' }));
    const single = screen.getByLabelText('Single');
    await waitFor(() => expect(single).toHaveFocus());
    const married = screen.getByLabelText('Married') as HTMLInputElement;
    act(() => married.focus());
    fireEvent.click(married);
    expect(screen.getByRole('radiogroup')).toBeInTheDocument();
    expect(save).not.toHaveBeenCalled();
    fireEvent.keyDown(married, { key: 'Enter' });
    await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
    expect(save).toHaveBeenCalledWith('married');
  });

  it('a viewer reads it with no pencil', () => {
    card(false);
    expect(screen.getByText('California')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Edit State' })).toBeNull();
  });
});
