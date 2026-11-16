// Steward's mark: an acorn with its oak leaf, on a rounded plum tile. The small thing an oak grows from, planted now
// for later, with a leaf off the stem so it reads as alive and growing. Drawn for the browser tab first: one bold
// shape on a rounded square (more pixels than a disc), and a separate hand-tuned 16 px drawing.
//   medium and large (32 grid, 20 px and up): the stem, the leaf (a softer tint, with a vein in the tile colour), the
//     cap and the nut. The cap's rim, the gap under it and the nut's top sit on whole pixels at 32 px;
//   tiny (16 grid, under 20 px): the same parts redrawn so every straight edge lands on a whole pixel at 16 px.
// The tile is a rounded square, its corner radius 22% of the side. The single source for ui/Mark.tsx (inline in the
// app) and scripts/make-icons.mjs (the favicon set). Plain data and string building only, so Node can load it without
// a build step.

export type MarkSize = 'large' | 'medium' | 'tiny';
/** What a part is painted with: the glyph's ink, the leaf's softer tint, or the tile colour (for lines cut into the ink). */
export type Paint = 'ink' | 'soft' | 'tile';
export type MarkPart = { d: string; fill?: Paint; stroke?: Paint; width?: number };
export type MarkArt = { grid: number; parts: MarkPart[] };

const STEM: MarkPart = { d: 'M14.6 8.2 15.6 4.6', stroke: 'ink', width: 2.2 };
const LEAF: MarkPart = { d: 'M16.4 6.4c1.6-3 5-4.4 9.4-3.6-.6 4.4-3.4 7-7.6 7-.6 0-1.2-.1-1.8-.3z', fill: 'soft' };
const VEIN: MarkPart = { d: 'M17 8.4 23.4 4.2', stroke: 'tile', width: 1 };
const CAP: MarkPart = { d: 'M4 15.2C4 11 8.6 8.4 14.5 8.4S25 11 25 15.2c0 1-.8 1.8-1.8 1.8H5.8c-1 0-1.8-.8-1.8-1.8z', fill: 'ink' };
const NUT: MarkPart = { d: 'M7 19h15c0 5.7-3 10-7.5 11.5C10 29 7 24.7 7 19z', fill: 'ink' };

export const MARK: Record<MarkSize, MarkArt> = {
  medium: { grid: 32, parts: [STEM, LEAF, VEIN, CAP, NUT] },
  // The same drawing: a lip line or cap texture was tried and read as a slot through the cap at 48 to 64 px.
  large: { grid: 32, parts: [STEM, LEAF, VEIN, CAP, NUT] },
  tiny: {
    grid: 16,
    parts: [
      { d: 'M7 2h1v3H7z', fill: 'ink' },
      { d: 'M8.5 4.2C9.2 2.4 11 1.5 13.6 1.8c-.3 2.4-1.9 3.6-4.2 3.6-.3 0-.6 0-.9-.1z', fill: 'soft' },
      { d: 'M2 8.5C2 6.3 4.5 5 7.5 5S13 6.3 13 8.5V9H2z', fill: 'ink' },
      { d: 'M4 10h7c0 2.8-1.5 4.6-3.5 5.4C5.5 14.6 4 12.8 4 10z', fill: 'ink' },
    ],
  },
};

/** The design for a size in CSS pixels: tiny below 20, medium below 48, large from 48. */
export function markSizeFor(px: number): MarkSize {
  return px < 20 ? 'tiny' : px < 48 ? 'medium' : 'large';
}

/** The tile's corner radius: 22% of the side. */
export const tileRadius = (grid: number) => grid * 0.22;

export type MarkColours = Record<Paint, string>;
export const LIGHT: MarkColours = { tile: '#7C3352', ink: '#FBF3F6', soft: '#E8C9D6' };
export const DARK: MarkColours = { tile: '#93446A', ink: '#FFFFFF', soft: '#F2D9E4' };

/** A standalone SVG of one design, for the favicon set. `square` paints a full-bleed square in the tile colour instead
 *  of the rounded tile (iOS and maskable launchers round it themselves); `scale` shrinks the glyph about the centre
 *  (padding for those masks); `darkMode` adds a prefers-color-scheme rule that switches to the dark colours. */
export function markSvg(size: MarkSize, opts: { colours?: MarkColours; square?: boolean; scale?: number; darkMode?: boolean } = {}): string {
  const a = MARK[size];
  const c = opts.colours ?? LIGHT;
  const g = a.grid;
  const h = g / 2;
  const s = opts.scale ?? 1;
  // Class names: f-<paint> for fills, l-<paint> for lines. Only the ones this design uses get a rule.
  const used = new Set<string>(['f-tile', ...a.parts.map((p) => (p.fill ? `f-${p.fill}` : `l-${p.stroke}`))]);
  const rules = (k: MarkColours) => [...used].map((cls) => `.${cls}{${cls[0] === 'f' ? 'fill' : 'stroke'}:${k[cls.slice(2) as Paint]}}`).join('');
  const style = opts.darkMode ? `<style>${rules(c)}@media (prefers-color-scheme:dark){${rules(DARK)}}</style>` : '';
  const paint = (kind: 'fill' | 'stroke', p: Paint) => (opts.darkMode ? `class="${kind === 'fill' ? 'f' : 'l'}-${p}"` : `${kind}="${c[p]}"`);
  const tile = opts.square
    ? `<rect width="${g}" height="${g}" ${paint('fill', 'tile')}/>`
    : `<rect width="${g}" height="${g}" rx="${tileRadius(g)}" ${paint('fill', 'tile')}/>`;
  const glyph = a.parts.map((p) => p.fill
    ? `<path d="${p.d}" ${paint('fill', p.fill)}/>`
    : `<path d="${p.d}" fill="none" stroke-width="${p.width}" stroke-linecap="round" ${paint('stroke', p.stroke!)}/>`).join('');
  const scaled = s === 1 ? glyph : `<g transform="translate(${h} ${h}) scale(${s}) translate(${-h} ${-h})">${glyph}</g>`;
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${g} ${g}">${style}${tile}${scaled}</svg>\n`;
}
