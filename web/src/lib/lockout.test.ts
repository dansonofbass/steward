import { describe, expect, it } from 'vitest';
import { lockoutMinutes } from './lockout';

describe('lockoutMinutes', () => {
  it('reads the minutes from the server message', () => {
    expect(lockoutMinutes('Too many tries. Try again in 15 minutes.')).toBe(15);
    expect(lockoutMinutes('Too many tries. Try again in 1 minute.')).toBe(1);
    expect(lockoutMinutes('Too many tries. Try again in 7 minutes.')).toBe(7);
  });
  it('falls back to 15 when the message has no number', () => {
    expect(lockoutMinutes('Something else')).toBe(15);
    expect(lockoutMinutes('')).toBe(15);
  });
});
