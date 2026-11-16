// A select in a Field keeps base.css's chevron (final review 1): Field.css may set the background colour, never the
// `background` shorthand, which would reset the chevron image on every select in a form.
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';

// Read as text: the test runner's CSS plugin returns an empty string for imported stylesheets.
const read = (rel: string) => readFileSync(new URL(rel, import.meta.url), 'utf8');

describe('Field.css and the select chevron', () => {
  it('never resets background-image on a select', () => {
    const field = read('./Field.css');
    const selectRules = [...field.matchAll(/([^{}]*select[^{}]*)\{([^}]*)\}/g)].map((m) => m[2]);
    expect(selectRules.length).toBeGreaterThan(0);
    for (const body of selectRules) expect(body).not.toMatch(/(^|[\s;])background\s*:/);
  });

  it('base.css draws the chevron on every select', () => {
    const base = read('../styles/base.css');
    expect(base).toMatch(/select \{ appearance: none;[^}]*background-image: url\("data:image\/svg\+xml/);
  });
});
