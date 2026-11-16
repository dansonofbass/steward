// Colour arithmetic for the palette tests: WCAG 2 relative luminance and contrast ratio. Test-only, like test-clock.ts.
export type Rgba = [number, number, number, number];

/** "#RRGGBB", "rgb(r, g, b)" or "rgba(r, g, b, a)" as [r, g, b, a]. */
export function rgba(c: string): Rgba {
  const s = c.trim();
  const hex = /^#([0-9a-f]{6})$/i.exec(s);
  if (hex) return [parseInt(hex[1].slice(0, 2), 16), parseInt(hex[1].slice(2, 4), 16), parseInt(hex[1].slice(4, 6), 16), 1];
  const fn = /^rgba?\(\s*(\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?\s*\)$/.exec(s);
  if (!fn) throw new Error(`not a colour: ${c}`);
  return [Number(fn[1]), Number(fn[2]), Number(fn[3]), fn[4] === undefined ? 1 : Number(fn[4])];
}

/** `c` as it shows laid over the opaque `ground`. */
export function over(c: string, ground: string): [number, number, number] {
  const [r, g, b, a] = rgba(c);
  const [R, G, B] = rgba(ground);
  return [r * a + R * (1 - a), g * a + G * (1 - a), b * a + B * (1 - a)];
}

export function luminance([r, g, b]: readonly number[]): number {
  const f = (v: number) => { const x = v / 255; return x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4; };
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
}

/** The contrast ratio of `fg` on the opaque `bg` (a translucent `fg`, such as --line, is first laid over `bg`). */
export function contrast(fg: string, bg: string): number {
  const a = luminance(over(fg, bg));
  const b = luminance(over(bg, bg));
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}
