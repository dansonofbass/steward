import { fireEvent, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { BookSummary } from '../api/types';
import { stubFetch, wrap } from '../test-utils';
import { BookCtx } from './BookContext';
import { BookSwitcher } from './BookSwitcher';

afterEach(() => vi.unstubAllGlobals());
const book = (slug: string, name: string, kind: 'household' | 'parent', role: 'manager' | 'viewer'): BookSummary =>
  ({ slug, name, kind, role, available: true, reason: null, owners: [], profile: null });
const OURS = book('ours', 'Ours', 'household', 'manager');
const MOM = book('mom', 'Mom (Robin\'s)', 'parent', 'viewer');
const me = (books: BookSummary[]) => ({ user: { id: 1, username: 'jr', display_name: 'JR' }, session: { id: 1, device_label: '', created_at: '' }, books });

function show(variant: 'rail' | 'bar', books: BookSummary[], path = '/b/ours/transactions') {
  stubFetch({ '/api/auth/me': me(books) });
  return wrap(<BookCtx.Provider value={OURS}><BookSwitcher variant={variant} /></BookCtx.Provider>, path);
}

describe('BookSwitcher', () => {
  it('on the phone opens a sheet listing my books, with kind and role, the current one marked', async () => {
    show('bar', [OURS, MOM]);
    fireEvent.click(await screen.findByRole('button', { name: 'Switch book: Ours' }));
    const sheet = screen.getByRole('dialog', { name: 'Books' });
    const ours = within(sheet).getByRole('link', { name: /Ours/ });
    expect(ours).toHaveAttribute('aria-current', 'true');
    expect(ours).toHaveTextContent('Household · Manager');
    const mom = within(sheet).getByRole('link', { name: /Mom \(Robin's\)/ });
    expect(mom).toHaveAttribute('href', '/b/mom/transactions');
    expect(mom).toHaveTextContent('Parent · Viewer');
    expect(within(sheet).getByRole('link', { name: 'All books' })).toHaveAttribute('href', '/b/ours/settings/books');
  });
  it('on the desktop opens a list under the button that Escape closes, giving focus back', async () => {
    show('rail', [OURS, MOM]);
    const button = await screen.findByRole('button', { name: 'Switch book: Ours, Household' });
    fireEvent.click(button);
    expect(button).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByRole('link', { name: /Mom/ })).toBeInTheDocument();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('link', { name: /Mom/ })).toBeNull();
    expect(document.activeElement).toBe(button);
  });
  it('tags the Sample', async () => {
    const sample: BookSummary = { ...book('sample', 'Sample household', 'household', 'manager'), sample: true };
    show('bar', [OURS, sample]);
    fireEvent.click(await screen.findByRole('button', { name: 'Switch book: Ours' }));
    const row = within(screen.getByRole('dialog', { name: 'Books' })).getByRole('link', { name: /Sample household/ });
    const tag = row.querySelector('.books__tag');
    expect(tag).toHaveTextContent('Made-up money');
    expect(row).not.toHaveTextContent('Household · Manager');
  });
  it('is not there for a person with one book', async () => {
    const { container } = show('bar', [OURS]);
    await new Promise((r) => setTimeout(r, 0));
    expect(container.querySelector('.books')).toBeNull();
  });
  it('a person in two books who manages neither still gets All books', async () => {
    stubFetch({ '/api/auth/me': me([MOM, book('dad', 'Dad', 'parent', 'viewer')]) });
    wrap(<BookCtx.Provider value={MOM}><BookSwitcher variant="bar" /></BookCtx.Provider>, '/b/mom');
    fireEvent.click(await screen.findByRole('button', { name: /Switch book/ }));
    expect(screen.getByRole('link', { name: 'All books' })).toHaveAttribute('href', '/b/mom/settings/books');
  });
});
