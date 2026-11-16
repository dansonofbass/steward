import { expect, it } from 'vitest';
import { initials } from './initials';
it('takes the first letters of the first two words, or the username', () => {
  expect(initials('JR Hale', 'jr')).toBe('JH');
  expect(initials('JR', 'jr')).toBe('JR');
  expect(initials('alex', 'alex')).toBe('A');
  expect(initials('', 'sam')).toBe('SA');
});
it('keeps an emoji whole, and treats a name of only spaces as no name', () => {
  expect(initials('🌻 Rose', 'rose')).toBe('🌻R');
  expect(initials('🌻', 'rose')).toBe('🌻');
  expect(initials('   ', 'sam')).toBe('SA');
});
