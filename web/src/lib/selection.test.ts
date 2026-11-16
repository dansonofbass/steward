import { describe, expect, it } from 'vitest';
import { picked } from './selection';

const ORDER = [5, 4, 3, 2, 1];

describe('picked (bulk sort: a click, and Shift for a range)', () => {
  it('flips the row clicked', () => {
    expect([...picked(new Set(), ORDER, 3, null)]).toEqual([3]);
    expect([...picked(new Set([3, 4]), ORDER, 3, null)]).toEqual([4]);
  });
  it('picks every row between the last one clicked and this one, in the list order, either way', () => {
    expect([...picked(new Set([4]), ORDER, 1, 4)].sort()).toEqual([1, 2, 3, 4]);
    expect([...picked(new Set([1]), ORDER, 4, 1)].sort()).toEqual([1, 2, 3, 4]);
  });
  it('keeps rows picked outside the range', () => {
    expect([...picked(new Set([5, 2]), ORDER, 1, 2)].sort()).toEqual([1, 2, 5]);
  });
  it('flips the row alone when the last one clicked is no longer on screen', () => {
    expect([...picked(new Set(), ORDER, 2, 99)]).toEqual([2]);
  });
});
