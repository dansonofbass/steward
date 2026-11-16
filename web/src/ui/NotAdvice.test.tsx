import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { NOT_ADVICE, NotAdvice } from './NotAdvice';

describe('NotAdvice', () => {
  it('says estimates, not advice', () => {
    render(<NotAdvice />);
    expect(NOT_ADVICE).toBe('Estimates, not financial or tax advice.');
    expect(screen.getByText(NOT_ADVICE)).toHaveClass('small', 'muted');
  });
});
