import { render, waitFor } from '@testing-library/react';
import { useRef } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Acorn } from './Acorn';
import { useAcornMotion, useWinMoment } from './useMoment';

const fx = vi.hoisted(() => ({ stop: vi.fn(), off: vi.fn(), acorn: vi.fn(), winMoment: vi.fn() }));
vi.mock('../celebrate/celebrate', () => ({
  acorn: (o: unknown) => { fx.acorn(o); return fx.stop; },
  winMoment: (o: unknown) => { fx.winMoment(o); return fx.off; },
}));
afterEach(() => { vi.clearAllMocks(); });

function Hopping({ motion, sound }: { motion: 'hop' | null; sound?: boolean }) {
  const svg = useRef<SVGSVGElement>(null);
  useAcornMotion(svg, motion, sound);
  return <Acorn ref={svg} face="win" season={null} />;
}
function Coins({ on }: { on: boolean }) {
  const host = useRef<HTMLParagraphElement>(null);
  useWinMoment(host, on ? 'coins' : null, true);
  return <p ref={host}>Payday came.</p>;
}

describe('handing motion to the celebrate chunk (phase 17)', () => {
  it('plays the motion on the acorn once, and stops it when the acorn goes', async () => {
    const { unmount, container } = render(<Hopping motion="hop" sound />);
    await waitFor(() => expect(fx.acorn).toHaveBeenCalledWith({ svg: container.querySelector('svg'), motion: 'hop', sound: true }));
    unmount();
    expect(fx.stop).toHaveBeenCalledOnce();
  });

  it('no motion asks for nothing', async () => {
    render(<Hopping motion={null} />);
    await Promise.resolve();
    expect(fx.acorn).not.toHaveBeenCalled();
  });

  it('with reduced motion the chunk is never asked, and the still acorn stays', async () => {
    vi.stubGlobal('matchMedia', (q: string) => ({ matches: q.includes('reduce'), media: q, addEventListener: () => {}, removeEventListener: () => {} }));
    const { container } = render(<Hopping motion="hop" />);
    await Promise.resolve();
    expect(fx.acorn).not.toHaveBeenCalled();
    expect(container.querySelector('svg.acorn')).not.toBeNull();
    // Control: without reduced motion the same render does ask, so the wait above was long enough to mean something.
    vi.unstubAllGlobals();
    render(<Hopping motion="hop" />);
    await waitFor(() => expect(fx.acorn).toHaveBeenCalledOnce());
  });

  it('a win moment plays over its host and comes off when the host goes', async () => {
    const { unmount, container } = render(<Coins on />);
    await waitFor(() => expect(fx.winMoment).toHaveBeenCalledWith({ host: container.querySelector('p'), name: 'coins', sound: true }));
    unmount();
    expect(fx.off).toHaveBeenCalledOnce();
  });
});
