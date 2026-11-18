// Home has no red (Home spec P5): problems read in ink, the red figure and every amber mark are --warn.
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

const read = (rel: string) => readFileSync(new URL(rel, import.meta.url), 'utf8');

describe("Home's CSS and red", () => {
  it('never uses --danger, and the red figure is --warn', () => {
    for (const file of ['./home.css', './home/strip.css']) expect(read(file)).not.toContain('--danger');
    expect(read('./home.css')).toMatch(/\.verdict__figure\.is-red\s*\{[^}]*color:\s*var\(--warn\)/);
  });
});
