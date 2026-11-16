import { describe, expect, it } from 'vitest';
import { ownerOptions } from './shared';

const ONE = [{ key: 'jr', label: 'Alex' }, { key: 'joint', label: 'Joint' }, { key: 'business', label: 'Business' }];

describe('ownerOptions (spec 2026-11-05, section 7)', () => {
  it("is the book's owners as the server names them", () => {
    expect(ownerOptions(ONE).map((o) => o.label)).toEqual(['Alex', 'Joint', 'Business']);
  });
  it('outside a book, the household four with plain labels', () => {
    expect(ownerOptions(undefined).map((o) => o.label)).toEqual(['Person 1', 'Person 2', 'Joint', 'Business']);
  });
  it("keeps an account's own owner when the book no longer offers it (a household of one)", () => {
    expect(ownerOptions(ONE, 'spouse').map((o) => [o.value, o.label])).toEqual(
      [['jr', 'Alex'], ['joint', 'Joint'], ['business', 'Business'], ['spouse', 'Person 2']]);
    expect(ownerOptions(ONE, 'joint')).toHaveLength(3);
  });
});
