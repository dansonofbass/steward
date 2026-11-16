import { readFileSync, readdirSync } from 'node:fs';
import { gzipSync } from 'node:zlib';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

// JR allows 190 KB while e2e "Home is interactive under 1.5 s" passes (reimbursable plan).
const LIMIT = 190 * 1024;
const dist = fileURLToPath(new URL('../dist/', import.meta.url));
const html = readFileSync(join(dist, 'index.html'), 'utf8');

// Read an attribute from a tag regardless of order or quote style.
const attr = (tag, name) => {
  const m = tag.match(new RegExp(`\\s${name}\\s*=\\s*(?:"([^"]*)"|'([^']*)'|([^\\s>]+))`, 'i'));
  return m ? (m[1] ?? m[2] ?? m[3]) : null;
};
// Turn a URL from index.html into a path under dist/, dropping any base path ("/", "./", "/steward/").
const rel = (u) => {
  const p = u.split(/[?#]/)[0];
  const i = p.lastIndexOf('assets/');
  return i >= 0 ? p.slice(i) : p.replace(/^(\.?\/)+/, '');
};

const js = new Set();
const css = new Set();
for (const tag of html.match(/<script\b[^>]*>/gi) ?? []) {
  const src = attr(tag, 'src');
  if (src && /\.m?js$/.test(src.split(/[?#]/)[0])) js.add(rel(src));
}
for (const tag of html.match(/<link\b[^>]*>/gi) ?? []) {
  const href = attr(tag, 'href');
  const relAttr = (attr(tag, 'rel') ?? '').toLowerCase();
  if (!href) continue;
  const path = href.split(/[?#]/)[0];
  if (relAttr.includes('modulepreload') && /\.m?js$/.test(path)) js.add(rel(href));
  else if (relAttr.includes('stylesheet') && path.endsWith('.css')) css.add(rel(href));
}
if (js.size === 0) { console.error('Bundle check: no entry script found in dist/index.html'); process.exit(1); }

let total = 0;
for (const f of [...js, ...css]) total += gzipSync(readFileSync(join(dist, f))).length;
const lazy = readdirSync(join(dist, 'assets')).filter((f) => f.endsWith('.js') && !js.has('assets/' + f));
console.log(`initial bundle: ${(total / 1024).toFixed(1)} KB gzipped (limit ${LIMIT / 1024} KB); ${js.size} JS + ${css.size} CSS files, ${lazy.length} lazy chunks`);
if (total > LIMIT) { console.error('Bundle budget exceeded'); process.exit(1); }
// Phase 17 (spec 1, Performance first): the line pools (lib/lines.ts) and the acorn's motion load only with the
// moments that use them. A pool line or a motion keyframe in the initial bundle fails the build.
const initialText = [...js].map((f) => readFileSync(join(dist, f), 'utf8')).join('\n');
for (const marker of ['Clean slate.', 'One in forty. Lucky you.', 'Big sort energy.', 'rotate(-6deg)']) {
  if (initialText.includes(marker)) { console.error(`Bundle check: "${marker}" is in the initial bundle; it belongs in a lazy chunk`); process.exit(1); }
}

// Lazy routes load on demand and each stays under 40 KB gzip (JS and CSS together).
// Plan: milestone 2 spec section 10.
function lazyBudget(name, limitKb) {
  const pattern = new RegExp(`^${name}-[\\w-]+\\.(js|css)$`);
  const files = readdirSync(join(dist, 'assets')).filter((f) => pattern.test(f));
  if (!files.some((f) => f.endsWith('.js'))) { console.error(`Bundle check: no lazy ${name} chunk (assets/${name}-*.js); the ${name} route must load on demand`); process.exit(1); }
  if (files.some((f) => js.has('assets/' + f) || css.has('assets/' + f))) { console.error(`Bundle check: the ${name} chunk is part of the initial bundle`); process.exit(1); }
  let size = 0;
  for (const f of files) size += gzipSync(readFileSync(join(dist, 'assets', f))).length;
  console.log(`${name} route: ${(size / 1024).toFixed(1)} KB gzipped (limit ${limitKb} KB); ${files.join(', ')}`);
  if (size > limitKb * 1024) { console.error(`${name} route budget exceeded`); process.exit(1); }
}
lazyBudget('Plan', 40);
lazyBudgetDeep('Profile', 40);
lazyBudget('Inventory', 40);
// Spending's pages stay lazy, each under its 40 KB (polish round, Performance).
lazyBudget('Spending', 40);
lazyBudget('Trends', 40);
lazyBudget('Targets', 40);
lazyBudget('SetAsides', 40);
// Settings → Chat (milestone 3 plan A).
lazyBudget('ChatSettings', 30);
// Get Steward ready (guided setup spec 3): the page, its panels and the pairing form.
lazyBudgetDeep('Ready', 16);
// The welcome, Help and the Sample's ribbon and Undo (guided setup spec 11, The bundle).
lazyBudgetDeep('Welcome', 24);
lazyBudgetDeep('Help', 4);
lazyBudget('About', 4);
lazyBudgetDeep('Sample', 6);
// The Business page (business plan).
lazyBudget('Business', 30);
lazyBudget('BusinessSettings', 30);
// The Ask page (milestone 3 spec section 12): its chunk and every non-initial chunk it imports, under 30 KB gzip.
function importsOf(file) {
  const src = readFileSync(join(dist, 'assets', file), 'utf8');
  return [...src.matchAll(/from\s*["']\.\/([\w.-]+\.js)["']/g)].map((m) => m[1]);
}
// `parents` are chunks already loaded when this one is (it is opened only from them): the walk skips them.
// `deepParents` are the same, with everything they import statically.
function lazyBudgetDeep(name, limitKb, parents = [], deepParents = []) {
  const pattern = new RegExp(`^${name}-[\\w-]+\\.js$`);
  const entry = readdirSync(join(dist, 'assets')).find((f) => pattern.test(f));
  if (!entry) { console.error(`Bundle check: no lazy ${name} chunk (assets/${name}-*.js)`); process.exit(1); }
  if (js.has('assets/' + entry)) { console.error(`Bundle check: the ${name} chunk is part of the initial bundle`); process.exit(1); }
  const seen = new Set();
  // A deep parent is loaded with everything it imports statically, so those chunks count as loaded too.
  const parentChunks = new Set();
  const walkParent = (f) => { if (parentChunks.has(f) || js.has('assets/' + f)) return; parentChunks.add(f); importsOf(f).forEach(walkParent); };
  for (const p of deepParents) readdirSync(join(dist, 'assets')).filter((f) => new RegExp(`^${p}-[\\w-]+\\.js$`).test(f)).forEach(walkParent);
  const loaded = (f) => js.has('assets/' + f) || parentChunks.has(f) || parents.some((p) => new RegExp(`^${p}-[\\w-]+\\.js$`).test(f));
  const walk = (f) => { if (seen.has(f) || loaded(f)) return; seen.add(f); importsOf(f).forEach(walk); };
  walk(entry);
  const cssFiles = readdirSync(join(dist, 'assets')).filter((f) => new RegExp(`^${name}-[\\w-]+\\.css$`).test(f));
  let size = 0;
  for (const f of [...seen, ...cssFiles]) size += gzipSync(readFileSync(join(dist, 'assets', f))).length;
  console.log(`${name} route: ${(size / 1024).toFixed(1)} KB gzipped with its imports (limit ${limitKb} KB); ${[...seen, ...cssFiles].join(', ')}`);
  if (size > limitKb * 1024) { console.error(`${name} route budget exceeded`); process.exit(1); }
}
lazyBudgetDeep('Ask', 30);
// Ask about this (phase 13, P26): the panel opens from many pages, so it is its own chunk; with what it shares with the
// Ask page (Composer, Conversation, useAsk) it stays under 30 KB gzip, and it is never in the initial bundle.
lazyBudgetDeep('AskPanel', 30);
// The Care screen (parent care plan): its chunk and every non-initial chunk it imports, under 30 KB gzip.
lazyBudgetDeep('Care', 30);
// The Taxes page (tax decisions plan).
lazyBudgetDeep('Taxes', 30);
// The celebrate chunk (sorting redesign, Performance 3): loaded on the first celebration of a visit, never part of the
// initial bundle, at most 12 KB gzip with its CSS and any non-initial chunk it imports.
lazyBudgetDeep('celebrate', 12);
// Net worth over time on Accounts (plan subpages): Accounts is in the initial bundle, so the chart is its own chunk.
lazyBudgetDeep('NetWorthChart', 8);
// The investment account page's sections (investment views spec): AccountPage is in the initial bundle, so its
// sections are their own chunk, with everything it imports that isn't initial.
lazyBudgetDeep('Investment', 20);
// Import positions opens from the investment page's chunk, so that chunk and its shared modules count as loaded.
lazyBudgetDeep('PositionsImport', 8, ['Investment']);
lazyBudgetDeep('LimitsTable', 8);
lazyBudgetDeep('NetWorthSplit', 6);
// Reimbursable expenses: the first-use prompt and chooser load on demand from the Review card and the detail.
lazyBudgetDeep('PayerInline', 8);
// The note form (polish round, item 5) loads on demand from the transaction detail and Review's Note.
lazyBudgetDeep('NoteForm', 8);
lazyBudgetDeep('Reimbursements', 20);
lazyBudgetDeep('Trip', 20);
// Same account, two feeds: the card on Home and Accounts, and Merge into… on an account's page, load on demand.
lazyBudgetDeep('SameAccount', 8);
lazyBudgetDeep('MergeInto', 8);
// Bulk sort (profile spec, Sorting several rows at once): the bar and the result line load at the first Select.
lazyBudgetDeep('BulkSort', 6);
// Home (phase 11 spec, Performance): the 12-month strip and Since you last looked load once Home is ready.
lazyBudgetDeep('MonthStrip', 6);
lazyBudgetDeep('HomeSince', 6);
// Phase 17: Home's moments (payday, the tree, the gateway back) and the line pools they share load once Home is ready.
lazyBudgetDeep('HomeMoments', 8);
// The Review page itself (review focus P26 fallback, JR: "On demand is fine"): eager Review overshot the initial limit by
// 0.2 KB and the lighter options (focus-only code in focus/, the reimbursement toast behind an import) saved under 0.1 KB.
lazyBudgetDeep('Review', 40);
// Review focus (P26): one card at a time, the gestures, the keys, the demo and the ⋯ menu load on demand, idle-preloaded.
lazyBudgetDeep('Focus', 20, ['Review']);
// Import (import/export spec P35): Settings › Import with everything it imports that isn't initial, under 20 KB gzip.
// It opens only inside Settings, whose chunk (WEB-19) is loaded by then with its imports, so what it shares with
// Settings (the shared icons that used to be initial) doesn't count.
lazyBudgetDeep('Import', 20, [], ['Settings']);
// Settings (WEB-19): the page and its in-place sections, out of the first download.
lazyBudgetDeep('Settings', 30);
// The layout check and row review (PDF statements spec P48): their own chunk, opened only from Import.
lazyBudgetDeep('Statements', 16, ['Import']);
// Export (import/export spec P35): the CSV links and the passphrase panel, under 8 KB gzip.
lazyBudgetDeep('Export', 8);
// Came from (JR, Oct 31): the detail's line and the file's bar on Transactions load on demand.
lazyBudgetDeep('CameFrom', 4);
lazyBudgetDeep('BatchBar', 6);
