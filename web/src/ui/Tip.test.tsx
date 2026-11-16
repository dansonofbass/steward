import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { Tip, tipLeft } from './Tip';

describe('tipLeft', () => {
  it('centres under the button when there is room', () => expect(tipLeft(195, 200, 390)).toBe(95));
  it('keeps 16 px from the left edge', () => expect(tipLeft(20, 280, 390)).toBe(16));
  it('keeps 16 px from the right edge', () => expect(tipLeft(380, 280, 390)).toBe(94));
  it('starts at the gutter when the text is wider than the screen', () => expect(tipLeft(100, 500, 320)).toBe(16));
});

describe('Tip', () => {
  it('opens on tap, describes the button, and closes on Escape', () => {
    render(<Tip>Nine in ten histories last.</Tip>);
    const btn = screen.getByRole('button', { name: 'What this means' });
    expect(screen.queryByRole('tooltip')).toBeNull();
    fireEvent.click(btn);
    expect(btn).toHaveAttribute('aria-expanded', 'true');
    const tip = screen.getByRole('tooltip');
    expect(tip).toHaveTextContent('Nine in ten histories last.');
    expect(btn).toHaveAttribute('aria-describedby', tip.id);
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(btn).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByRole('tooltip')).toBeNull();
  });

  it('closes when you tap elsewhere', () => {
    render(<><Tip>Text</Tip><p>Elsewhere</p></>);
    fireEvent.click(screen.getByRole('button', { name: 'What this means' }));
    fireEvent.pointerDown(screen.getByText('Elsewhere'));
    expect(screen.queryByRole('tooltip')).toBeNull();
  });
});
