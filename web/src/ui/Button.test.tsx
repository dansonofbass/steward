import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { useFakeTimers } from '../test-clock';
import { Button } from './Button';

afterEach(() => vi.useRealTimers());

describe('Button busy', () => {
  it('stays focusable, ignores clicks, and shows the spinner only after 100 ms', () => {
    useFakeTimers();
    const onClick = vi.fn();
    const { container } = render(<Button busy onClick={onClick}>Save</Button>);
    const btn = screen.getByRole('button');
    expect(btn).not.toBeDisabled();
    expect(btn).toHaveAttribute('aria-disabled', 'true');
    expect(btn).toHaveAttribute('aria-busy', 'true');
    fireEvent.click(btn);
    expect(onClick).not.toHaveBeenCalled();
    expect(container.querySelector('.btn__spinner')).toBeNull();
    act(() => { vi.advanceTimersByTime(100); });
    expect(container.querySelector('.btn__spinner')).not.toBeNull();
  });
  it('an explicit disabled prop still disables', () => {
    render(<Button disabled>Save</Button>);
    expect(screen.getByRole('button')).toBeDisabled();
  });
  it('a busy submit button does not submit its form; an idle one does', () => {
    const onSubmit = vi.fn((e: { preventDefault: () => void }) => e.preventDefault());
    const { rerender } = render(<form onSubmit={onSubmit}><Button type="submit" busy>Save</Button></form>);
    fireEvent.click(screen.getByRole('button'));
    expect(onSubmit).not.toHaveBeenCalled();
    rerender(<form onSubmit={onSubmit}><Button type="submit" busy={false}>Save</Button></form>);
    fireEvent.click(screen.getByRole('button'));
    expect(onSubmit).toHaveBeenCalledOnce();
  });
});
