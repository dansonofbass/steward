import { render } from '@testing-library/react';
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { Mark } from './Mark';
import { DARK, LIGHT, MARK, markSizeFor, markSvg } from './markArt';

const svg = (el: HTMLElement) => el.querySelector('svg') as SVGSVGElement;
// The path goes through a plain variable so the bundler doesn't turn the URL into an asset link.
const at = (rel: string) => new URL(rel, import.meta.url);

describe('Mark', () => {
  it('picks the drawing tuned for its size', () => {
    expect([12, 16, 19].map(markSizeFor)).toEqual(['tiny', 'tiny', 'tiny']);
    expect([20, 24, 28, 32, 47].map(markSizeFor)).toEqual(['medium', 'medium', 'medium', 'medium', 'medium']);
    expect([48, 64, 180].map(markSizeFor)).toEqual(['large', 'large', 'large']);
  });

  it('draws the acorn with its leaf on a rounded tile from 20 px, on the 32 grid', () => {
    for (const size of [28, 64]) {
      const s = svg(render(<Mark size={size} />).container);
      expect(s).toHaveAttribute('width', String(size));
      expect(s).toHaveAttribute('viewBox', '0 0 32 32');
      const tile = s.querySelector('.brand-mark__tile');
      expect(tile).toHaveAttribute('width', '32');
      expect(tile).toHaveAttribute('rx', '7.04');   // 22% of the side
      expect(s.querySelectorAll('.brand-mark__ink')).toHaveLength(2);    // the cap and the nut
      expect(s.querySelectorAll('.brand-mark__soft')).toHaveLength(1);   // the leaf
      expect(s.querySelector('.brand-mark__ink-line')).toHaveAttribute('stroke-width', '2.2');   // the stem
      expect(s.querySelector('.brand-mark__tile-line')).toHaveAttribute('stroke-width', '1');    // the leaf's vein
      expect(s.querySelector('circle')).toBeNull();
    }
    expect(svg(render(<Mark size={28} />).container)).toHaveAttribute('data-size', 'medium');
    expect(svg(render(<Mark size={64} />).container)).toHaveAttribute('data-size', 'large');
  });

  it('draws the pixel-aligned 16 grid acorn below 20 px', () => {
    const s = svg(render(<Mark size={16} />).container);
    expect(s).toHaveAttribute('data-size', 'tiny');
    expect(s).toHaveAttribute('viewBox', '0 0 16 16');
    expect(s.querySelector('.brand-mark__tile')).toHaveAttribute('rx', '3.52');
    expect([...s.querySelectorAll('path')].map((p) => p.getAttribute('d'))).toEqual(MARK.tiny.parts.map((p) => p.d));
  });

  it('keeps the straight edges of the 32 grid acorn on whole pixels: the cap rim at y 17, the nut top at y 19', () => {
    const [, , , cap, nut] = MARK.medium.parts;
    expect(cap.d).toMatch(/c0 1-\.8 1\.8-1\.8 1\.8H5\.8/);   // from y 15.2 down 1.8 to 17
    expect(cap.d).toMatch(/^M4 15\.2/);
    expect(nut.d).toMatch(/^M7 19h15/);
  });

  it('is decorative by default and an image when labelled', () => {
    const quiet = svg(render(<Mark size={28} />).container);
    expect(quiet).toHaveAttribute('aria-hidden', 'true');
    expect(quiet).not.toHaveAttribute('role');
    const named = svg(render(<Mark size={64} label="Steward" />).container);
    expect(named).toHaveAttribute('role', 'img');
    expect(named).toHaveAccessibleName('Steward');
    expect(named).not.toHaveAttribute('aria-hidden');
  });

  it('takes its colours from the theme, not fixed fills', () => {
    const s = svg(render(<Mark size={64} />).container);
    for (const el of s.querySelectorAll('rect, path')) expect(el.getAttribute('fill') ?? 'none').toBe('none');
    const css = readFileSync(at('./Mark.css'), 'utf8');
    expect(css).toContain('.brand-mark__tile { fill: var(--mark-tile, var(--accent)); }');
    expect(css).toContain(`.brand-mark__ink { fill: var(--mark-ink, ${LIGHT.ink}); }`);
    expect(css).toContain(`.brand-mark__soft { fill: var(--mark-soft, ${LIGHT.soft}); }`);
    const tokens = readFileSync(at('../styles/tokens.css'), 'utf8');
    expect(tokens).toContain(`--mark-tile: ${DARK.tile};`);
    expect(tokens).toContain(`--mark-ink: ${DARK.ink};`);
    expect(tokens).toContain(`--mark-soft: ${DARK.soft};`);
  });
});

describe('The favicon set', () => {
  const pub = (name: string) => at('../../public/' + name);

  it('favicon.svg is the 16 grid acorn on its tile, switching to the dark tile in dark mode (regenerate with npm run icons)', () => {
    const file = readFileSync(pub('favicon.svg'), 'utf8');
    expect(file).toBe(markSvg('tiny', { darkMode: true }));
    expect(file).toContain('<rect width="16" height="16" rx="3.52" class="f-tile"/>');
    expect(file).toContain(`.f-tile{fill:${LIGHT.tile}}.f-ink{fill:${LIGHT.ink}}.f-soft{fill:${LIGHT.soft}}`);
    expect(file).toContain(`@media (prefers-color-scheme:dark){.f-tile{fill:${DARK.tile}}.f-ink{fill:${DARK.ink}}.f-soft{fill:${DARK.soft}}}`);
    expect(file).not.toContain('circle');
  });

  it('has every PNG at its size', () => {
    const size = (name: string) => {
      const b = readFileSync(pub(name));
      expect(String.fromCharCode(...b.subarray(1, 4))).toBe('PNG');
      const v = new DataView(b.buffer, b.byteOffset, b.byteLength);
      return [v.getUint32(16), v.getUint32(20)];   // the IHDR chunk's width and height
    };
    expect(size('favicon-16.png')).toEqual([16, 16]);
    expect(size('favicon-32.png')).toEqual([32, 32]);
    expect(size('apple-touch-icon.png')).toEqual([180, 180]);
    expect(size('icon-192.png')).toEqual([192, 192]);
    expect(size('icon-512.png')).toEqual([512, 512]);
    expect(size('icon-512-maskable.png')).toEqual([512, 512]);
  });
});
