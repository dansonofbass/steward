import { render } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { Acorn, acornSeason, FACE_LINES } from './Acorn';

const at = (y: number, m: number, d: number, h = 12, min = 0) => new Date(y, m - 1, d, h, min);
const svgOf = (c: HTMLElement) => c.querySelector<SVGSVGElement>('svg.acorn')!;

describe('the acorn companion (phase 17 spec 3.1)', () => {
  it.each(['win', 'golden', 'resting', 'oops'] as const)("draws the %s face on the mark's acorn, without its tile", (face) => {
    const svg = svgOf(render(<Acorn face={face} season={null} />).container);
    expect(svg).toHaveAttribute('data-face', face);
    expect(svg.querySelector('rect')).toBeNull();
    expect(svg.querySelector('.acorn__face')).toHaveAttribute('d', FACE_LINES[face]);
    expect(svg.querySelectorAll('.acorn__eye')).toHaveLength(face === 'win' ? 2 : 0);
    expect(svg.querySelectorAll('.acorn__sweat')).toHaveLength(face === 'oops' ? 1 : 0);
    expect(svg.classList.contains('acorn--golden')).toBe(face === 'golden');
    expect(svg.querySelector('[data-move]')).not.toBeNull();
    expect(svg).toHaveAttribute('aria-hidden', 'true');
  });

  it('the faces are the Nov 2 drawings: dot eyes and a smile, arched eyes, closed eyes, > < with a wavy mouth', () => {
    expect(FACE_LINES).toEqual({
      win: 'M13 26.2q1.5 1 3 0',
      golden: 'M10.8 23.6q1.2-1.6 2.4 0M15.8 23.6q1.2-1.6 2.4 0M12.8 26q1.7 1.3 3.4 0',
      resting: 'M10.8 23q1.2.9 2.4 0M15.8 23q1.2.9 2.4 0',
      oops: 'M10.6 21.8l2.2 1.3-2.2 1.3M18.4 21.8l-2.2 1.3 2.2 1.3M13.2 26.6q1.3-.8 2.6 0',
    });
  });

  it('is an image with a name when given a label, and takes its size', () => {
    const svg = svgOf(render(<Acorn face="win" label="Steward" size={48} season={null} />).container);
    expect(svg).toHaveAttribute('role', 'img');
    expect(svg).toHaveAttribute('aria-label', 'Steward');
    expect([svg.getAttribute('width'), svg.getAttribute('height')]).toEqual(['48', '48']);
  });

  it('the leaf turns from Oct 1 to Nov 30 and the snow cap sits on Dec 1 to 31, by the local date', () => {
    expect(acornSeason(at(2026, 9, 30, 23, 59))).toBeNull();
    expect(acornSeason(at(2026, 10, 1, 0, 0))).toBe('fall');
    expect(acornSeason(at(2026, 11, 30, 23, 59))).toBe('fall');
    expect(acornSeason(at(2026, 12, 1, 0, 0))).toBe('snow');
    expect(acornSeason(at(2026, 12, 31, 23, 59))).toBe('snow');
    expect(acornSeason(at(2027, 1, 1, 0, 0))).toBeNull();       // Jan 1's fireworks are the streamers', not the acorn's
  });

  it("reads today from the device's clock (the fake clock here)", () => {
    vi.setSystemTime(at(2026, 12, 1, 0, 0));
    const snow = svgOf(render(<Acorn face="win" />).container);
    expect(snow).toHaveAttribute('data-season', 'snow');
    expect(snow.querySelector('.acorn__snow')).not.toBeNull();
    vi.setSystemTime(at(2026, 10, 30));
    const fall = svgOf(render(<Acorn face="win" />).container);
    expect(fall.classList.contains('acorn--fall')).toBe(true);
    expect(fall.querySelector('.acorn__snow')).toBeNull();
    vi.setSystemTime(at(2027, 3, 3));
    expect(svgOf(render(<Acorn face="win" />).container)).not.toHaveAttribute('data-season');
  });
});
