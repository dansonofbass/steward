// Phase 18: a .br and a .gz beside each built asset over 1 KB, so steward.web sends the copy the browser takes
// (606 KB of JS and CSS went out uncompressed). Node's own zlib: no new dependency. Fonts and images are already
// compressed, so they are left alone.
import { brotliCompressSync, constants, gzipSync } from 'node:zlib';
import { readdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const assets = fileURLToPath(new URL('../dist/assets/', import.meta.url));
const PACK = /\.(js|css|svg|json)$/;
const MIN = 1024;
let raw = 0;
let br = 0;
let gz = 0;
let n = 0;
for (const f of readdirSync(assets)) {
  if (!PACK.test(f)) continue;
  const data = readFileSync(join(assets, f));
  if (data.length < MIN) continue;
  const b = brotliCompressSync(data, { params: { [constants.BROTLI_PARAM_QUALITY]: 11, [constants.BROTLI_PARAM_SIZE_HINT]: data.length } });
  const g = gzipSync(data, { level: 9 });
  writeFileSync(join(assets, `${f}.br`), b);
  writeFileSync(join(assets, `${f}.gz`), g);
  raw += data.length; br += b.length; gz += g.length; n += 1;
}
console.log(`precompressed ${n} assets: ${(raw / 1024).toFixed(0)} KB → br ${(br / 1024).toFixed(0)} KB, gzip ${(gz / 1024).toFixed(0)} KB`);
