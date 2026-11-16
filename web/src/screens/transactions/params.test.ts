import { expect, it } from 'vitest';
import { withParam } from './params';

it('merges q into the live params without dropping a filter chosen in the meantime', () => {
  expect(withParam('?dates=all&category=dining', 'q', 'green').toString()).toBe('dates=all&category=dining&q=green');
});
it('replaces and removes', () => {
  expect(withParam('q=a&x=1', 'q', 'b').toString()).toBe('q=b&x=1');
  expect(withParam('q=a&x=1', 'q', '').toString()).toBe('x=1');
});
