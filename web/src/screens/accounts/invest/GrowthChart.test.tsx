import { render } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { GrowthChart } from './GrowthChart';
import { PAGE } from './fixtures';

afterEach(() => vi.unstubAllGlobals());

const media = (wide: boolean) => vi.stubGlobal('matchMedia', (q: string) => ({ matches: wide, media: q, addEventListener: () => {}, removeEventListener: () => {} }));

describe('GrowthChart', () => {
  // The drawing is a fixed size per screen class, so its labels render at text size instead of scaling with the column.
  it.each([[false, '-48 -10 372 174', false], [true, '-48 -10 912 274', true]])('draws once at the size useWide picks (wide %s)', (wide, box, cls) => {
    media(wide);
    const { container } = render(<GrowthChart points={PAGE.series} since={PAGE.since} today={new Date('2026-10-20')} />);
    const svgs = container.querySelectorAll('svg');
    expect(svgs).toHaveLength(1);
    expect(svgs[0].getAttribute('viewBox')).toBe(box);
    expect(svgs[0].classList.contains('is-wide')).toBe(cls);
  });
});
