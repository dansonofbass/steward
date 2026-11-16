import { render } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { AuthPanel } from './AuthPanel';

describe('The sign-in frame', () => {
  it('shows the large mark and "Steward" above the card on sign-in', () => {
    const r = render(<MemoryRouter><AuthPanel><p>form</p></AuthPanel></MemoryRouter>);
    const brand = r.container.querySelector('.login__brand') as HTMLElement;
    expect(brand.querySelector('svg.brand-mark')).toHaveAttribute('data-size', 'large');
    expect(r.getByRole('heading', { level: 1, name: 'Steward' }).parentElement).toBe(brand);
    expect(brand.nextElementSibling).toHaveClass('login__panel--card');
  });

  it('keeps the small wordmark and the heading on forgot and reset, without the mark', () => {
    const r = render(<MemoryRouter><AuthPanel heading="Forgot your password?"><p>form</p></AuthPanel></MemoryRouter>);
    expect(r.container.querySelector('.brand-mark')).toBeNull();
    expect(r.getByRole('heading', { level: 1 })).toHaveTextContent('Forgot your password?');
    expect(r.getByRole('link', { name: 'Steward' })).toHaveAttribute('href', '/login');
  });
});
