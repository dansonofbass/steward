import { describe, expect, it } from 'vitest';
import { safeNext } from './AuthPanel';

describe('safeNext', () => {
  it.each([
    ['//x', '/'],
    ['/\\x', '/'],
    ['https://x', '/'],
    [null, '/'],
    ['/review?x=1', '/review?x=1'],
  ])('%s -> %s', (input, expected) => {
    expect(safeNext(input)).toBe(expected);
  });
});
