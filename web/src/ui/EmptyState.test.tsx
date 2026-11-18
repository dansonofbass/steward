import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { EmptyState } from './EmptyState';

// Issue #21: an empty state's sentence is not a heading, so moving by headings never lands on it. Only an empty state
// that is the whole screen (no book to open) gives the screen its level 1 heading.
describe('EmptyState', () => {
  it('sets its title as a paragraph, not a heading', () => {
    render(<EmptyState title="No rules yet." body="Rules sort new transactions." />);
    expect(screen.queryByRole('heading')).toBeNull();
    expect(screen.getByText('No rules yet.').tagName).toBe('P');
  });

  it('is the level 1 heading when it is the whole screen', () => {
    render(<EmptyState page title="No books yet" />);
    expect(screen.getByRole('heading', { level: 1, name: 'No books yet' })).toBeTruthy();
  });
});
