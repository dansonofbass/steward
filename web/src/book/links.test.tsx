import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import type { BookSummary } from '../api/types';
import { BookCtx, bookHref } from './BookContext';
import { inBook, Link } from './links';

const MOM: BookSummary = { slug: 'mom', name: 'Mom', kind: 'parent', role: 'viewer', available: true, reason: null, owners: [], profile: null };

describe('links inside a book', () => {
  it('put absolute in-app paths in the book and leave sign-in pages and book paths alone', () => {
    const p = (to: string) => bookHref('mom', to);
    expect(inBook('/', p)).toBe('/b/mom');
    expect(inBook('/settings/banks', p)).toBe('/b/mom/settings/banks');
    expect(inBook('/cashflow?month=2026-10', p)).toBe('/b/mom/cashflow?month=2026-10');
    for (const to of ['/login?next=%2F', '/forgot', '/reset?token=x', '/design', '/b/ours/plan', 'relative', 'https://www.redfin.com/']) {
      expect(inBook(to, p)).toBe(to);
    }
  });
  it('Link uses the open book, or ours outside one', () => {
    render(<MemoryRouter><BookCtx.Provider value={MOM}><Link to="/review">Review</Link></BookCtx.Provider><Link to="/review">Ours</Link></MemoryRouter>);
    expect(screen.getByRole('link', { name: 'Review' })).toHaveAttribute('href', '/b/mom/review');
    expect(screen.getByRole('link', { name: 'Ours' })).toHaveAttribute('href', '/b/ours/review');
  });
});
