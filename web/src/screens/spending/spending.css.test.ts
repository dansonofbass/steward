// Spending has no red (polish round): --danger is for a field the server would refuse, never an over state.
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';

const read = (rel: string) => readFileSync(new URL(rel, import.meta.url), 'utf8');

describe('spending.css and red', () => {
  it('uses --danger only for field errors', () => {
    const rules = [...read('./spending.css').matchAll(/([^{}]+)\{([^}]*)\}/g)].filter((m) => m[2].includes('--danger'));
    expect(rules.length).toBeGreaterThan(0);
    for (const [, selector] of rules) expect(selector).toMatch(/field-error|aria-invalid|savebar__error/);
  });
});
