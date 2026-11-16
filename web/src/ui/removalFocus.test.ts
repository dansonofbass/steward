// THO-1 and THO-12 (release gate 0.1.0, fix 16f): after a confirmed removal, a word and a place for focus. A scan of
// every source checks the class, so a new removal can't bring it back:
// - every ConfirmSheet says where focus goes when it closes. A removal's sheet takes a useRemoval's returnTo, and its
//   file says what went with a line from its copy file and renders the RemovalLine. Any other returnTo is listed below
//   with its reason;
// - no button is named by a removal word alone ("Remove", "Delete", "Revoke"): its name says its target.
import { describe, expect, it } from 'vitest';

const SOURCES: Record<string, string> = Object.fromEntries(
  Object.entries(import.meta.glob<string>('/src/**/*.tsx', { query: '?raw', import: 'default', eager: true }))
    .filter(([path]) => !/\.test\.[jt]sx?$/.test(path)),
);

/** The ConfirmSheets whose focus doesn't follow a removal, with why. Keyed "path returnTo". */
const OTHER_FOCUS: Record<string, string> = {
  '/src/screens/settings/Members.tsx BACK_TO_OPENER': 'a role change keeps its select, which opened the sheet',
  '/src/frame/YouMenu.tsx BACK_TO_OPENER': 'signing out leaves the page; a cancel goes back to the You button',
  '/src/screens/ready/GatewayPanel.tsx toPairForm': "Pair again opens the pairing form, and focus goes to its code box",
};

/** The design page shows the danger button style with a sample label; it removes nothing. */
const NOT_A_REMOVAL = new Set(['/src/screens/Design.tsx']);

/** A button whose whole text is one of these says only the action, not what it acts on. */
const BARE = new Set(['{REMOVE}', '{C.REMOVE}', '{DELETE}', '{C.DELETE}', '{C.CC_REVOKE}', '{REMOVE_THIS_ONE}', 'Remove', 'Delete', 'Revoke']);

/** The opening tag that starts at `start` ("<Name ..."), read up to its closing ">" outside braces and strings. */
function openingTag(src: string, start: number): string {
  let depth = 0;
  for (let i = start + 1; i < src.length; i++) {
    const c = src[i];
    if (c === '{') depth++;
    else if (c === '}') depth--;
    else if (c === '"' || (depth > 0 && (c === "'" || c === '`'))) {
      const end = src.indexOf(c, i + 1);
      i = end === -1 ? src.length : end;
    } else if (c === '>' && depth === 0) return src.slice(start, i + 1);
  }
  return src.slice(start);
}

function tags(src: string, name: string): { tag: string; at: number }[] {
  return [...src.matchAll(new RegExp(`<${name}\\b`, 'g'))].map((m) => ({ tag: openingTag(src, m.index!), at: m.index! }));
}

const returnToOf = (tag: string) => /\breturnTo=\{([^}]*)\}/.exec(tag)?.[1].trim() ?? null;
const REMOVED_CALL = /\.removed(?:Here)?\(\s*([^,)]*)/g;
const FROM_COPY = /^(?:(?:C\.)?fill\(\s*)?(?:C\.)?[A-Z][A-Z0-9_]*\b/;

/** Every ConfirmSheet with what's wrong with its focus or its line, "path: problem". */
function sheetProblems(sources: Record<string, string>): { sheets: number; used: Set<string>; problems: string[] } {
  const problems: string[] = [];
  const used = new Set<string>();
  const lineChecked = new Set<string>();
  let sheets = 0;
  for (const [path, src] of Object.entries(sources)) {
    for (const { tag } of tags(src, 'ConfirmSheet')) {
      sheets++;
      const to = returnToOf(tag);
      if (to === null) { problems.push(`${path}: a ConfirmSheet with no returnTo`); continue; }
      if (!/^\w+\.returnTo$/.test(to)) {
        if (OTHER_FOCUS[`${path} ${to}`]) used.add(`${path} ${to}`);
        else problems.push(`${path}: returnTo={${to}} is neither a useRemoval's returnTo nor listed with a reason`);
        continue;
      }
      if (lineChecked.has(path)) continue;
      lineChecked.add(path);
      const calls = [...src.matchAll(REMOVED_CALL)].map((m) => m[1].trim());
      if (calls.length === 0) problems.push(`${path}: a removal's sheet, but nothing says what went (.removed(...))`);
      for (const arg of calls) if (!FROM_COPY.test(arg)) problems.push(`${path}: .removed(${arg}) says a line that isn't from a copy file`);
      if (!src.includes('<RemovalLine')) problems.push(`${path}: a removal's sheet, but no RemovalLine shows the line`);
    }
  }
  return { sheets, used, problems };
}

/** Every button named by a removal word alone, "path: <tag>". */
function bareButtons(sources: Record<string, string>): { checked: number; hits: string[] } {
  const hits: string[] = [];
  let checked = 0;
  for (const [path, src] of Object.entries(sources)) {
    if (NOT_A_REMOVAL.has(path)) continue;
    for (const name of ['Button', 'button']) {
      for (const { tag, at } of tags(src, name)) {
        if (tag.endsWith('/>')) continue;
        const close = src.indexOf(`</${name}>`, at + tag.length);
        if (close === -1) continue;
        const text = src.slice(at + tag.length, close).trim();
        if (!BARE.has(text)) continue;
        checked++;
        if (!/\baria-label=/.test(tag)) hits.push(`${path}: ${tag.replace(/\s+/g, ' ').slice(0, 120)}`);
      }
    }
  }
  return { checked, hits };
}

describe('after a confirmed removal, a word and a place for focus (THO-1, THO-12)', () => {
  it('ConfirmSheet requires returnTo, so a caller without one fails tsc', () => {
    const src = SOURCES['/src/ui/ConfirmSheet.tsx'];
    expect(src).toMatch(/\n\s*returnTo: \(\) => HTMLElement \| null;/);
    expect(src).not.toMatch(/returnTo\?:/);
  });

  it('every ConfirmSheet sends focus somewhere that still exists, and a removal says what went from its copy file', () => {
    const { sheets, used, problems } = sheetProblems(SOURCES);
    expect(sheets).toBeGreaterThanOrEqual(15);   // the scan reads the sheets, not nothing
    expect(problems).toEqual([]);
    expect([...used].sort()).toEqual(Object.keys(OTHER_FOCUS).sort());   // no stale entry
  });

  it('no button is named by a removal word alone', () => {
    const { checked, hits } = bareButtons(SOURCES);
    expect(checked).toBeGreaterThanOrEqual(10);
    expect(hits).toEqual([]);
  });

  it('the scan catches each shape it looks for', () => {
    const removal = (body: string) => ({ '/src/x.tsx': body });
    expect(sheetProblems(removal('<ConfirmSheet open onConfirm={() => go()} />')).problems).toEqual(['/src/x.tsx: a ConfirmSheet with no returnTo']);
    expect(sheetProblems(removal('<ConfirmSheet open returnTo={BACK_TO_OPENER} />')).problems[0]).toMatch(/neither a useRemoval/);
    expect(sheetProblems(removal('<RemovalLine removal={r} /><ConfirmSheet open onConfirm={() => r.removed("Gone.")} returnTo={r.returnTo} />')).problems)
      .toEqual(['/src/x.tsx: .removed("Gone.") says a line that isn\'t from a copy file']);
    expect(sheetProblems(removal('<ConfirmSheet open returnTo={r.returnTo} />')).problems).toHaveLength(2);
    expect(sheetProblems(removal('<RemovalLine removal={r} /><ConfirmSheet open onConfirm={() => r.removed(fill(C.GONE, { a }))} returnTo={r.returnTo} />')).problems).toEqual([]);
    expect(bareButtons({ '/src/x.tsx': '<Button variant="quiet" onClick={() => go(a > b)}>{C.REMOVE}</Button>' }).hits).toHaveLength(1);
    expect(bareButtons({ '/src/x.tsx': '<Button aria-label={`Remove ${k.name}`} onClick={() => go()}>{REMOVE}</Button>' }).hits).toEqual([]);
  });
});
