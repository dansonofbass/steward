import { describe, expect, it } from 'vitest';
import * as copy from './copy';

describe("Profile's words (JR's lean-copy rule)", () => {
  it('say nothing the control already says', () => {
    const all = JSON.stringify(copy);
    for (const banned of ['any time', 'in steps of', 'is saved when']) expect(all.toLowerCase()).not.toContain(banned);
  });
});
