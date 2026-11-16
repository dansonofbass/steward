// The app's stylesheets as text, for the CSS tests (the test runner's CSS plugin returns an empty string for an imported
// stylesheet). Paths are relative to web/src. Test-only.
import { readdirSync, readFileSync } from 'node:fs';

/** The dark sky phases, as every dark-only rule names them (sky.css gives these three color-scheme: dark). */
export const DARK = ':root:is([data-phase="night"], [data-phase="dawn"], [data-phase="dusk"])';

// The path goes through a function so the bundler doesn't turn the URL into an asset link.
const at = (rel: string) => new URL(rel, import.meta.url);
export const readCss = (rel: string): string => readFileSync(at(rel), 'utf8');
export const uncomment = (css: string): string => css.replace(/\/\*[\s\S]*?\*\//g, '');
const squash = (s: string) => s.replace(/\s+/g, ' ').trim();

/** Every stylesheet under web/src, as [path, text without comments]. */
export function allCss(): [string, string][] {
  return readdirSync(at('.'), { recursive: true, encoding: 'utf8' })
    .filter((f) => f.endsWith('.css'))
    .map((f) => [f, uncomment(readCss(f))]);
}

/** A selector list split at its top-level commas (not the ones inside :is(), :where() or :not()). */
export function selectors(list: string): string[] {
  const out: string[] = [];
  let depth = 0;
  let start = 0;
  for (let i = 0; i < list.length; i++) {
    const ch = list[i];
    if (ch === '(') depth++;
    else if (ch === ')') depth--;
    else if (ch === ',' && depth === 0) { out.push(squash(list.slice(start, i))); start = i + 1; }
  }
  out.push(squash(list.slice(start)));
  return out.filter(Boolean);
}

/** Every innermost rule of a stylesheet (those inside @media too): its selectors and its declarations, squashed. */
export function rules(css: string): { sel: string[]; body: string }[] {
  return [...uncomment(css).matchAll(/([^{}]+)\{([^{}]*)\}/g)].map((m) => ({ sel: selectors(m[1]), body: squash(m[2]) }));
}

/** The declarations of the first rule whose selector list holds `selector`, or '' when there is none. */
export function rule(css: string, selector: string): string {
  const want = squash(selector);
  return rules(css).find((r) => r.sel.includes(want))?.body ?? '';
}

/** The declarations of the dark-phase rule for `selector`: one whose list holds both `${DARK} ${selector}` and
 *  `.theme-dark ${selector}`, or '' when there is none. */
export function darkRule(css: string, selector: string): string {
  const a = squash(`${DARK} ${selector}`);
  const b = squash(`.theme-dark ${selector}`);
  return rules(css).find((r) => r.sel.includes(a) && r.sel.includes(b))?.body ?? '';
}
