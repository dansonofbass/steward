import { screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { wrapBook } from '../../test-utils';
import { Attention } from './Attention';

const ITEMS = [{ id: 1, message: "Big Bank couldn't sync.", kind: 'sync_failed' }];

describe('Needs a look', () => {
  it('links a manager to Banks and lets them dismiss the row', () => {
    wrapBook(<Attention items={ITEMS} />);
    expect(screen.getByRole('link', { name: 'Go to Settings' })).toHaveAttribute('href', '/b/ours/settings/banks');
    expect(screen.getByRole('button', { name: "Dismiss: Big Bank couldn't sync." })).toBeInTheDocument();
  });

  it('gives a viewer the rows to read, and no link or Dismiss, which only a manager has', () => {
    wrapBook(<Attention items={ITEMS} />, { role: 'viewer' });
    expect(screen.getByText("Big Bank couldn't sync.")).toBeInTheDocument();
    expect(screen.getByText('A manager of this book can sort these out in Settings.')).toBeInTheDocument();
    expect(screen.queryByRole('link')).toBeNull();
    expect(screen.queryByRole('button')).toBeNull();
  });
});
