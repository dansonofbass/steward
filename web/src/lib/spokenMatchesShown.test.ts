// Gate class (THO-2, THO-10, THO-11): what a screen reader hears differs from what the screen shows. Three shapes, each
// scanned across every source:
//  1. A state shown by an icon only. A ternary picks a tick or a cross (or any two icons), the icon is aria-hidden, and
//     the words beside it stay the same: Settings › Chat said "Categorizer is answering" beside a red cross.
//  2. Parts that run together. A separator hidden from a screen reader takes the space with it ("$108,000about 11
//     years earlier"), so every hidden dot goes through ui/Sep, which keeps the spaces outside the hidden part. A dot
//     drawn by CSS carries empty alt text, or a screen reader reads it glued to the word before ("personal·").
//  3. A hidden mark between two runs of text with no space ("The markis today").
import { readdirSync, readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

const SOURCES: Record<string, string> = Object.fromEntries(
  Object.entries(import.meta.glob<string>('/src/**/*.tsx', { query: '?raw', import: 'default', eager: true }))
    .filter(([path]) => !/\.test\.[jt]sx?$/.test(path)),
);

// Read as text: the test runner's CSS plugin returns an empty string for imported stylesheets. The path goes through
// a function so the bundler doesn't turn the URL into an asset link.
const at = (rel: string) => new URL(rel, import.meta.url);
const STYLES: Record<string, string> = Object.fromEntries(
  readdirSync(at('..'), { recursive: true, encoding: 'utf8' }).filter((f) => f.endsWith('.css'))
    .map((f) => [`/src/${f}`, readFileSync(at(`../${f}`), 'utf8')]),
);

/** Icon ternaries whose state reaches a screen reader some other way than the two rules below, with how. */
const ALLOWED: Record<string, string> = {
  '/src/ui/ChecklistRow.tsx :: done': 'status is a required prop: the row\'s state in words, beside the icon',
  '/src/screens/chat/Chip.tsx :: isModelChip(chip)': "the pop's first line (chipWhy) names the layer in words",
  "/src/screens/inventory/AttachFile.tsx :: r.state === 'done'": 'the line under the name is the state in words: the upload, Attached, or why it was refused',
  "/src/screens/inventory/Suggestions.tsx :: a.icon === 'check'": "the answer's line is set with its icon and says the answer in words",
  '/src/screens/spending/setasides/SetAside.tsx :: r.paid': 'headState(r).text beside it says the state in words, paid included',
  "/src/screens/inventory/ItemPage.tsx :: f.content_type.startsWith('image/')": "a file's kind, not a state; the line under its name says the kind (f.label)",
  "/src/screens/spending/setasides/SetAsideForm.tsx :: item === 'car'": "an item's picture beside its label, not a state",
  '/src/screens/you/SignInDevices.tsx :: /iPhone|iPad|Android/.test(s.device_label)': "a device's kind, read from the device's name shown beside it",
};

type Hit = { key: string; at: number; end: number; cond: string };

const esc = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const norm = (s: string) => s.replace(/\s+/g, ' ').trim();

/** The lucide icons a source imports. */
function lucideNames(src: string): Set<string> {
  const names = new Set<string>();
  for (const m of src.matchAll(/import\s*\{([^}]*)\}\s*from\s*['"]lucide-react['"]/g)) {
    for (const part of m[1].split(',')) {
      const name = part.replace(/^\s*type\s+/, '').split(/\s+as\s+/).pop()!.trim();
      if (name) names.add(name);
    }
  }
  return names;
}

/** Every place a condition picks between two icons: inline (`{c ? <Check aria-hidden /> : <X ... />}`) or through a
 *  variable (`const Icon = c ? Check : X`). */
function iconTernaries(path: string, src: string): Hit[] {
  const hits: Hit[] = [];
  const inline = /\{\s*([^{}?]+?)\s*\?\s*<([A-Z]\w*)\b[^>]*?aria-hidden="true"[^>]*?\/>\s*:\s*(?:[^{}<]*?\?\s*)?<[A-Z]\w*/g;
  for (const m of src.matchAll(inline)) {
    const cond = norm(m[1]);
    hits.push({ key: `${path} :: ${cond}`, at: m.index, end: m.index + m[0].length, cond });
  }
  const icons = lucideNames(src);
  const assigned = /(?:const|let)\s+[A-Z]\w*\s*=\s*([^;?\n]+?)\s*\?\s*([A-Z]\w*)\s*:\s*([^;\n]+)/g;
  for (const m of src.matchAll(assigned)) {
    if (!icons.has(m[2])) continue;
    const cond = norm(m[1]);
    hits.push({ key: `${path} :: ${cond}`, at: m.index, end: m.index + m[0].length, cond });
  }
  return hits;
}

/** The condition reaches a screen reader as an ARIA state (a disclosure's chevron follows aria-expanded). */
const saidByAria = (src: string, cond: string) =>
  new RegExp(`aria-(?:expanded|pressed|checked|selected|current)=\\{\\s*${esc(cond).replace(/ /g, '\\s*')}\\s*\\}`).test(src);

/** The same condition picks the words shown beside the icon: a JSX child `{cond ? words : words}` just after it. */
function saidInWords(src: string, hit: Hit): boolean {
  const after = src.slice(hit.end, hit.end + 400);
  return new RegExp(`(?<=[>}]\\s*)\\{\\s*${esc(hit.cond).replace(/ /g, '\\s*')}\\s*\\?\\s*(?!<)`).test(after);
}

function unspokenStates(sources: Record<string, string>): { all: Hit[]; bad: string[] } {
  const all = Object.entries(sources).flatMap(([path, src]) => iconTernaries(path, src));
  const bad = all.filter((h) => !(h.key in ALLOWED) && !saidByAria(sources[h.key.split(' :: ')[0]], h.cond)
    && !saidInWords(sources[h.key.split(' :: ')[0]], h)).map((h) => h.key);
  return { all, bad };
}

const SEPARATOR = '[·•|/—–]';

/** Hidden separators written by hand: `<span aria-hidden="true"> · </span>`. Only ui/Sep may hold one. */
function handRolledSeparators(sources: Record<string, string>): string[] {
  const re = new RegExp(`<span\\b[^>]*aria-hidden="true"[^>]*>\\s*${SEPARATOR}\\s*</span>`, 'g');
  return Object.entries(sources).filter(([path]) => path !== '/src/ui/Sep.tsx')
    .flatMap(([path, src]) => [...src.matchAll(re)].map((m) => `${path}: ${m[0]}`));
}

/** A separator drawn by CSS (`content: '·'`) with no alt text after a slash, which a screen reader reads aloud. The
 *  plain declaration may stay as the fallback for a browser without alt text, when the same rule then gives the alt. */
function spokenCssSeparators(styles: Record<string, string>): string[] {
  const bad: string[] = [];
  for (const [path, css] of Object.entries(styles)) {
    for (const rule of css.replace(/\/\*[\s\S]*?\*\//g, '').matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
      const decls = rule[2];
      const plain = new RegExp(`content:\\s*(['"])\\s*${SEPARATOR}\\s*\\1\\s*(?:;|$)`).test(decls);
      const alt = new RegExp(`content:\\s*(['"])\\s*${SEPARATOR}\\s*\\1\\s*/\\s*(['"])\\2`).test(decls);
      if (plain && !alt) bad.push(`${path}: ${norm(rule[1])}`);
    }
  }
  return bad;
}

/** An empty hidden mark between two text expressions with nothing between: `{A}<span aria-hidden="true" />{B}`. */
function glued(sources: Record<string, string>): string[] {
  const re = /\}<([a-z]+)\b[^>]*aria-hidden="true"[^>]*(?:\/>|><\/\1>)\{/g;
  const spaced = (src: string) => src.replace(/\{\s*(['"`])\s+\1\s*\}/g, ' ');   // {' '} is a space
  return Object.entries(sources).flatMap(([path, src]) => [...spaced(src).matchAll(re)].map((m) => `${path}: ${m[0]}`));
}

describe('a screen reader hears what the screen shows', () => {
  it('a state shown by an icon is also said: by an ARIA state, by words the same condition picks, or as listed', () => {
    const { all, bad } = unspokenStates(SOURCES);
    expect(all.length).toBeGreaterThanOrEqual(8);          // the scan still finds the ternaries it was written for
    expect(bad).toEqual([]);
  });

  it('has no stale entries in the allowed list', () => {
    const keys = new Set(unspokenStates(SOURCES).all.map((h) => h.key));
    expect(Object.keys(ALLOWED).filter((k) => !keys.has(k))).toEqual([]);
  });

  it('every hidden separator goes through ui/Sep, so the parts around it keep their spaces', () => {
    expect(handRolledSeparators(SOURCES)).toEqual([]);
  });

  it('a separator drawn by CSS has empty alt text', () => {
    expect(Object.keys(STYLES).length).toBeGreaterThan(20);
    expect(spokenCssSeparators(STYLES)).toEqual([]);
  });

  it('no hidden mark sits between two runs of text with no space', () => {
    expect(glued(SOURCES)).toEqual([]);
  });

  // The scans themselves, on the shapes the gate found, so a scan that stops matching fails here and not silently.
  it('the scans catch each shape the gate found', () => {
    const chat = { '/x.tsx': `<li>{on ? <Check size={20} aria-hidden="true" /> : <X size={20} aria-hidden="true" />}{label}</li>` };
    expect(unspokenStates(chat).bad).toEqual(['/x.tsx :: on']);
    const oak = { '/x.tsx': `{m.met ? <Check className="i" size={16} aria-hidden="true" /> : <Circle className="i" size={16} aria-hidden="true" />}\n<span>{name}</span>` };
    expect(unspokenStates(oak).bad).toEqual(['/x.tsx :: m.met']);
    const variable = { '/x.tsx': `import { Check, X } from 'lucide-react';\nconst Icon = ok ? Check : X;\nreturn <li className={ok ? 'a' : 'b'}><Icon aria-hidden="true" />{label}</li>;` };
    expect(unspokenStates(variable).bad).toEqual(['/x.tsx :: ok']);
    const words = { '/x.tsx': `import { Check, X } from 'lucide-react';\nconst Icon = ok ? Check : X;\nreturn <li><Icon aria-hidden="true" />{ok ? words[0] : words[1]}</li>;` };
    expect(unspokenStates(words).bad).toEqual([]);
    const disclosure = { '/x.tsx': `<button aria-expanded={isOpen}>{isOpen ? <ChevronDown aria-hidden="true" /> : <ChevronRight aria-hidden="true" />}</button>` };
    expect(unspokenStates(disclosure).bad).toEqual([]);

    expect(handRolledSeparators({ '/x.tsx': `{a}<span className="sep" aria-hidden="true">·</span>{b}` })).toHaveLength(1);
    expect(handRolledSeparators({ '/x.tsx': `<Button>Undo</Button>\n<span aria-hidden="true"> · </span>` })).toHaveLength(1);
    expect(spokenCssSeparators({ '/x.css': `.a > span:not(:last-child)::after { content: '·'; margin-left: 4px; }` })).toHaveLength(1);
    expect(spokenCssSeparators({ '/x.css': `.a::after { content: '·'; content: '·' / ''; }` })).toEqual([]);
    expect(glued({ '/x.tsx': `<p>{A}<span className="mark" aria-hidden="true" />{B}</p>` })).toHaveLength(1);
    expect(glued({ '/x.tsx': `<p>{A}{' '}<span className="mark" aria-hidden="true" />{' '}{B}</p>` })).toEqual([]);
  });
});
