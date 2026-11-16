import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { Money } from './Money';

describe('Money', () => {
  it('marks direction and keeps digits tabular', () => {
    render(<Money cents={-5412} />);
    const el = screen.getByText('−$54.12');
    expect(el).toHaveClass('money', 'money--out');
    render(<Money cents={100} />);
    expect(screen.getByText('$1.00')).toHaveClass('money--in');
  });
});
