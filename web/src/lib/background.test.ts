import { describe, expect, it } from 'vitest';
import { backgroundLine } from './background';

describe('backgroundLine', () => {
  it('shows progress out of done plus pending', () => {
    expect(backgroundLine({ pending: 420, done: 230, waiting: false })).toBe('Categorizing in the background: 230 of 650');
  });
  it('says it is waiting for the gateway', () => {
    expect(backgroundLine({ pending: 650, done: 0, waiting: true })).toBe('Waiting for the gateway to categorize 650');
    expect(backgroundLine({ pending: 650, done: 0, waiting: true, expected: true })).toBe('Waiting for the gateway to categorize 650');
  });
  it('is null when no categorizer is coming: no gateway, or one with no local model (INS-21)', () => {
    expect(backgroundLine({ pending: 1, done: 0, waiting: true, expected: false })).toBeNull();
  });
  it('is null when nothing is pending, waiting or not', () => {
    expect(backgroundLine({ pending: 0, done: 0, waiting: true })).toBeNull();
    expect(backgroundLine({ pending: 0, done: 650, waiting: false })).toBeNull();
  });
});
