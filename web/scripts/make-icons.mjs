// Generates the favicon set in public/ from the mark's drawings in src/ui/markArt.ts (Steward's acorn with its leaf).
// Run from web/: npm run icons   (node 22.18+ loads the .ts art directly; Playwright's Chromium does the rasterizing)
//   favicon.svg            the 16 grid design on the rounded tile, switching to the dark tile under prefers-color-scheme: dark
//   favicon-16.png         the 16 grid design, transparent corners
//   favicon-32.png         the 32 grid design, transparent corners
//   apple-touch-icon.png   180, the acorn on a full-bleed plum square (iOS rounds the corners)
//   icon-192.png, icon-512.png       the rounded tile, transparent corners (manifest purpose "any")
//   icon-512-maskable.png  the acorn on a full-bleed plum square, all of it inside the 40% safe circle
import { writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { chromium } from '@playwright/test';
import { markSvg } from '../src/ui/markArt.ts';

const pub = (name) => fileURLToPath(new URL(`../public/${name}`, import.meta.url));
// The leaf's tip, the acorn's farthest point from the centre, is 16.4 of 32 out. iOS rounds about a fifth of the side,
// so 0.86 leaves the tip clear of the corner. Maskable launchers crop to as little as a 40% circle: at 0.74 the tip is
// at 38% of the width.
const APPLE_SCALE = 0.86;
const MASKABLE_SCALE = 0.74;

writeFileSync(pub('favicon.svg'), markSvg('tiny', { darkMode: true }));

const browser = await chromium.launch();
const page = await browser.newPage({ deviceScaleFactor: 1 });
async function png(name, svg, px) {
  const src = `data:image/svg+xml;base64,${Buffer.from(svg).toString('base64')}`;
  await page.setContent(`<body style="margin:0;background:transparent"><img id="i" src="${src}" width="${px}" height="${px}" style="display:block"></body>`);
  await page.locator('#i').evaluate((img) => img.decode());
  await page.locator('#i').screenshot({ path: pub(name), omitBackground: true });
  console.log(`public/${name}  ${px}x${px}`);
}
try {
  await png('favicon-16.png', markSvg('tiny'), 16);
  await png('favicon-32.png', markSvg('medium'), 32);
  await png('apple-touch-icon.png', markSvg('large', { square: true, scale: APPLE_SCALE }), 180);
  await png('icon-192.png', markSvg('large'), 192);
  await png('icon-512.png', markSvg('large'), 512);
  await png('icon-512-maskable.png', markSvg('large', { square: true, scale: MASKABLE_SCALE }), 512);
} finally {
  await browser.close();
}
console.log('public/favicon.svg');
