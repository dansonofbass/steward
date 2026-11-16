import { fireEvent, render, screen, within } from '@testing-library/react';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { BACK_TO_OPENER, useRemoval } from '../lib/useRemoval';
import { RemovalLine } from './RemovalLine';
import { ConfirmSheet } from './ConfirmSheet';

describe('ConfirmSheet', () => {
  it('names the action in the title, says what happens and what stays, and acts only on the confirm button', () => {
    const onConfirm = vi.fn();
    const onClose = vi.fn();
    render(<ConfirmSheet open title="Unlink SimpleFIN?" body="Your accounts and transactions stay; syncing stops." action="Unlink" onConfirm={onConfirm} onClose={onClose} returnTo={BACK_TO_OPENER} />);
    const sheet = screen.getByRole('dialog', { name: 'Unlink SimpleFIN?' });
    expect(within(sheet).getByText('Your accounts and transactions stay; syncing stops.')).toBeInTheDocument();
    fireEvent.click(within(sheet).getByRole('button', { name: 'Cancel' }));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onConfirm).not.toHaveBeenCalled();
    fireEvent.click(within(sheet).getByRole('button', { name: 'Unlink' }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });
  it('takes another word for the way out, and shows the error inside the sheet', () => {
    render(<ConfirmSheet open title="Delete it?" action="Delete" cancel="Keep" error="That didn't finish." onConfirm={() => {}} onClose={() => {}} returnTo={BACK_TO_OPENER} />);
    const sheet = screen.getByRole('dialog', { name: 'Delete it?' });
    expect(within(sheet).getByRole('button', { name: 'Keep' })).toBeInTheDocument();
    expect(within(sheet).getByText("That didn't finish.")).toBeInTheDocument();
  });
  it('renders nothing while closed', () => {
    render(<ConfirmSheet open={false} title="Remove?" action="Remove" onConfirm={() => {}} onClose={() => {}} returnTo={BACK_TO_OPENER} />);
    expect(screen.queryByRole('dialog')).toBeNull();
  });
  it('after a removal, focus goes to the anchor and the line is said; after a cancel, back to the row\'s button (THO-1)', () => {
    function List() {
      const [rows, setRows] = useState(['Vee', 'Sam']);
      const [asking, setAsking] = useState<string | null>(null);
      const removal = useRemoval();
      return (
        <section>
          <h2 ref={removal.anchor} tabIndex={-1}>People</h2>
          <RemovalLine removal={removal} />
          {rows.map((r) => <button key={r} type="button" onClick={() => setAsking(r)}>{`Remove ${r}`}</button>)}
          <ConfirmSheet open={asking !== null} title={`Remove ${asking}?`} action="Remove" returnTo={removal.returnTo} onClose={() => setAsking(null)}
            onConfirm={() => { setRows((all) => all.filter((r) => r !== asking)); removal.removed(`Removed ${asking}.`); setAsking(null); }} />
        </section>
      );
    }
    render(<List />);
    const vee = screen.getByRole('button', { name: 'Remove Vee' });
    vee.focus();
    fireEvent.click(vee);
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Cancel' }));
    expect(vee).toHaveFocus();
    vee.focus();
    fireEvent.click(vee);
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Remove' }));
    expect(screen.queryByRole('button', { name: 'Remove Vee' })).toBeNull();
    expect(screen.getByRole('heading', { name: 'People' })).toHaveFocus();
    expect(screen.getByText('Removed Vee.').closest('[aria-live="polite"]')).not.toBeNull();
  });
});
