// All of the app's CSS is global and lands on the page together, so a bare class styled in two files merges: the
// Accounts tab's `.kind` picked up Inventory's `.kind { display: flex }` and every card became a row. This fails when a
// bare top-level class (`.name` alone, not `.screen.accounts` or `.nav .item`) is defined in more than one stylesheet.
// A second screen that needs its own look prefixes its class (`.inv-seg`, `.book-kind`); only list a class below if
// the copies really are meant to compose, with the reason.
import { describe, expect, it } from 'vitest';
import { readdirSync, readFileSync } from 'node:fs';

// Read as text: the test runner's CSS plugin returns an empty string for imported stylesheets. The path goes through
// a function so the bundler doesn't turn the URL into an asset link.
const src = (rel: string) => new URL(rel, import.meta.url);

const ALLOWED: Record<string, string> = {
  'btn--block': 'identical `width: 100%` in Auth.css and transactions.css',
  or: 'identical divider rule in Auth.css and Settings.css',
  'grid-2': 'identical two-column grid in Settings.css and transactions.css',
  line: 'transactions.css is a port of the Settings.css row; Settings only adds justify-content, which a Filters row ignores',
  lines: 'transactions.css is a port of the Settings.css card; it only adds list-style and margin resets, which are no-ops on a Card',
  'set-row__sub': 'identical muted sub-line in chat.css and watching.css',
  'device-form': 'identical column form, capped at 560 px, in members.css and SignInDevices.css',
  money: 'base.css gives every .money tabular digits; Money.css adds nowrap on top',
  'theme-light': 'sky.css sets the palette variables, tokens.css resets the mark\'s dark colours, base.css the page background and ink for the same class',
  'theme-dark': 'sky.css and tokens.css set variables, base.css the page background and ink for the same class',
};

/** Selectors of the top-level rules in a stylesheet (rules inside @media and other at-rules are skipped). */
function topLevelSelectors(css: string): string[] {
  const text = css.replace(/\/\*[\s\S]*?\*\//g, '');
  const selectors: string[] = [];
  let depth = 0;
  let start = 0;
  let open = 0;
  for (let i = 0; i < text.length; i++) {
    if (text[i] === '{') {
      if (depth === 0) open = i;
      depth++;
    } else if (text[i] === '}') {
      depth--;
      if (depth === 0) {
        const selector = text.slice(start, open).trim();
        if (!selector.startsWith('@')) selectors.push(...selector.split(',').map((s) => s.trim()));
        start = i + 1;
      }
    }
  }
  return selectors;
}

function bareClassDefinitions(): Map<string, Set<string>> {
  const found = new Map<string, Set<string>>();
  for (const file of readdirSync(src('..'), { recursive: true, encoding: 'utf8' }).filter((f) => f.endsWith('.css'))) {
    for (const selector of topLevelSelectors(readFileSync(src(`../${file}`), 'utf8'))) {
      const name = /^\.([\w-]+)$/.exec(selector)?.[1];
      if (name) found.set(name, (found.get(name) ?? new Set()).add(file));
    }
  }
  return found;
}

describe('Global CSS class names', () => {
  const found = bareClassDefinitions();

  it('are each styled by one stylesheet, unless listed as shared', () => {
    const clashes = [...found].filter(([name, files]) => files.size > 1 && !(name in ALLOWED));
    expect(clashes.map(([name, files]) => `.${name}: ${[...files].join(', ')}`)).toEqual([]);
  });

  it('have no stale entries in the shared list', () => {
    const stale = Object.keys(ALLOWED).filter((name) => (found.get(name)?.size ?? 0) < 2);
    expect(stale).toEqual([]);
  });
});
