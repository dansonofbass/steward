import { fireEvent, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { wrapBook } from '../test-utils';
import { ChecklistRow } from './ChecklistRow';

describe('ChecklistRow', () => {
  it('is a link with a to, a button with an onClick, and still with neither', () => {
    const open = vi.fn();
    wrapBook(<><ChecklistRow done={false} status="To do" title="A" go="Add" to="/plan" testId="r" />
      <ChecklistRow done={false} needs title="B" go="Edit" onClick={open} expanded={false} status="Needs you" testId="r" />
      <ChecklistRow done status="Done" title="C" testId="r" /></>);
    const [a, b, c] = screen.getAllByTestId('r');
    expect(a.tagName).toBe('A');
    expect(b.tagName).toBe('BUTTON');
    expect(b).toHaveAttribute('aria-expanded', 'false');
    expect(b).toHaveClass('is-needs');
    expect(b).toHaveTextContent('Needs you');
    fireEvent.click(b);
    expect(open).toHaveBeenCalled();
    expect(c).toHaveClass('is-done', 'is-still');
  });
});
