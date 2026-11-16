// WEB-4 (release gate 0.1.0, fix 16i): a failed save is heard. A scan of every source keeps errors on the path that
// makes them heard:
// - a field's error is shown by Field, which ties it to its control and moves focus to it after a submit (or says it
//   when it comes any other way); an error about the whole form is a FormError, an alert. Nothing else draws the
//   field__error look;
// - a source that marks fields aria-invalid itself is listed, with what moves focus to them;
// - a Field with an error sits in a <form> (the submit watcher focuses it), or in a form that saves as you go, listed
//   here, where Field says the error politely.
import { describe, expect, it } from 'vitest';

const SOURCES: Record<string, string> = Object.fromEntries(
  Object.entries(import.meta.glob<string>('/src/**/*.tsx', { query: '?raw', import: 'default', eager: true }))
    .filter(([path]) => !/\.test\.[jt]sx?$/.test(path)),
);

/** Sources that tie an error to a field by hand, with what moves focus to it. `needs` must be in the source. */
const OWN_WIRING: Record<string, { why: string; needs: RegExp }> = {
  '/src/screens/export/Export.tsx': { why: 'its two passphrase boxes share one hint; a <form>, so the submit watcher focuses them', needs: /<form[^>]*onSubmit=/ },
  '/src/screens/spending/Targets.tsx': { why: 'one Save for many rows; it focuses the first bad row itself', needs: /getElementById\(inputId\(bad\)\)\?\.focus\(\)/ },
};

/** Forms with no submit: they save as you go, so an error comes after you have moved on and Field says it politely. */
const SAVES_AS_YOU_GO: Record<string, string> = {
  '/src/screens/profile/field.tsx': "Profile's fields save as you type or leave them",
  '/src/screens/profile/kids/KidsList.tsx': "a kid's row saves as you leave it",
  '/src/screens/profile/kids/Plans.tsx': 'a college plan row saves as you leave it',
  '/src/screens/profile/home/NewThing.tsx': 'a new home or car saves as you leave its fields',
  '/src/screens/profile/home/Payoff.tsx': 'the paid-off date saves as you change it',
  '/src/screens/Design.tsx': 'the design page shows the error style; it saves nothing',
};

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

function problems(sources: Record<string, string>): { fieldsWithErrors: number; problems: string[] } {
  const out: string[] = [];
  let fieldsWithErrors = 0;
  for (const [path, src] of Object.entries(sources)) {
    if (path === '/src/ui/Field.tsx') continue;
    if (/className="field__error"/.test(src) && !(path in OWN_WIRING)) out.push(`${path}: an error drawn by hand; use Field, or FormError for the whole form`);
    if (/aria-invalid|'aria-invalid'|ariaInvalid/.test(src)) {
      const own = OWN_WIRING[path];
      if (!own) out.push(`${path}: aria-invalid set by hand and not listed`);
      else if (!own.needs.test(src)) out.push(`${path}: listed, but what moves focus to its errors is gone`);
    }
    const withError = [...src.matchAll(/<Field\b/g)].filter((m) => /\berror=/.test(openingTag(src, m.index!)));
    fieldsWithErrors += withError.length;
    if (withError.length && !/<form\b/.test(src) && !(path in SAVES_AS_YOU_GO)) out.push(`${path}: a Field with an error in no <form>, and not listed as saving as you go`);
  }
  return { fieldsWithErrors, problems: out };
}

describe('field errors are heard (WEB-4)', () => {
  it('every source keeps its errors on the path a screen reader hears', () => {
    const { fieldsWithErrors, problems: found } = problems(SOURCES);
    expect(fieldsWithErrors).toBeGreaterThanOrEqual(30);       // floor: the scan still finds the Fields it checks
    expect(found).toEqual([]);
  });

  it('the lists never go stale', () => {
    for (const path of [...Object.keys(OWN_WIRING), ...Object.keys(SAVES_AS_YOU_GO)]) expect(SOURCES[path], path).toBeDefined();
    for (const path of Object.keys(SAVES_AS_YOU_GO)) expect(SOURCES[path], path).toMatch(/<Field\b[^>]*\berror=/s);
  });

  it('catches each shape it looks for', () => {
    const planted = {
      '/src/a.tsx': '<p className="field__error">{error}</p>',
      '/src/b.tsx': '<input aria-invalid={bad} />',
      '/src/c.tsx': '<div><Field label="Name" error={e}><input /></Field></div>',
      '/src/d.tsx': '<form onSubmit={save}><Field label="Name"\n  error={e}><input /></Field></form>',
    };
    expect(problems(planted).problems).toEqual([
      '/src/a.tsx: an error drawn by hand; use Field, or FormError for the whole form',
      '/src/b.tsx: aria-invalid set by hand and not listed',
      '/src/c.tsx: a Field with an error in no <form>, and not listed as saving as you go',
    ]);
  });
});
