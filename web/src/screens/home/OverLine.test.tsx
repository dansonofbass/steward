import { screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { renderAt } from '../../test-utils';
import { OverLineView } from './OverLine';

describe("the over line's view", () => {
  it('amber has the triangle; muted and quiet have no icon; names link in the book', () => {
    const { unmount } = renderAt(<OverLineView line={{ tone: 'amber', bits: [{ text: 'Eating out is $140 over its target' }, { text: ' · ' }, { text: 'See Eating out', to: '/spending/dining?month=2026-10' }] }} />, {}, '/');
    const line = screen.getByTestId('over-line');
    expect(line).toHaveClass('is-amber');
    expect(line.querySelector('svg')).not.toBeNull();
    expect(screen.getByRole('link', { name: 'See Eating out' })).toHaveAttribute('href', '/b/ours/spending/dining?month=2026-10');
    unmount();
    renderAt(<OverLineView line={{ tone: 'muted', bits: [{ text: 'Eating out is a little over its target · $512 of $500' }] }} />, {}, '/');
    expect(screen.getByTestId('over-line').querySelector('svg')).toBeNull();
  });
});
