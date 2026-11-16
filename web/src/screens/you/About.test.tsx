import { screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { stubFetch, wrap } from '../../test-utils';
import { NOT_ADVICE } from '../../ui/NotAdvice';
import About from './About';
import { LICENSE_LINE, NOT_AFFILIATED, SITE_URL, SOURCE_URL } from './aboutCopy';

afterEach(() => vi.unstubAllGlobals());

describe('About Steward', () => {
  it('shows the version, the not-advice line, the license and the source', async () => {
    stubFetch({ '/api/health': { ok: true, version: '0.1.0' } });
    wrap(<About />);
    expect(screen.getByRole('heading', { level: 1, name: 'About Steward' })).toBeInTheDocument();
    expect(await screen.findByText('Version 0.1.0')).toBeInTheDocument();
    expect(screen.getByText(NOT_ADVICE)).toBeInTheDocument();
    expect(screen.getByText(LICENSE_LINE)).toBeInTheDocument();
    const source = screen.getByRole('link', { name: 'Source code' });
    expect(source).toHaveAttribute('href', SOURCE_URL);
    expect(source).toHaveAttribute('rel', expect.stringContaining('noreferrer'));
    expect(screen.getByText(NOT_AFFILIATED)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'stewardmoney.app' })).toHaveAttribute('href', SITE_URL);
  });

  it('shows no version line until health answers', () => {
    stubFetch({ '/api/health': () => new Promise<Response>(() => {}) });
    wrap(<About />);
    expect(screen.queryByText(/^Version/)).not.toBeInTheDocument();
    expect(screen.getByText(NOT_ADVICE)).toBeInTheDocument();
  });
});
