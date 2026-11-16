import { describe, expect, it } from 'vitest';
import { freshness } from './freshness';

const today = new Date(2026, 9, 27);

describe('freshness', () => {
  it('flags a bank feed 3 or more days behind with its age', () => {
    expect(freshness({ source: 'simplefin', as_of: '2026-10-12', stale_days: 15 }, today)).toEqual({ text: '15 days old', stale: true });
    expect(freshness({ source: 'simplefin', as_of: '2026-10-24', stale_days: 3 }, today).stale).toBe(true);
  });

  it('says when a fresh feed was last updated, without a flag', () => {
    const f = freshness({ source: 'simplefin', as_of: '2026-10-26', stale_days: 1 }, today);
    expect(f.stale).toBe(false);
    expect(f.text).toMatch(/^Last updated /);
  });

  it('never flags an account kept by hand, however old', () => {
    const f = freshness({ source: 'manual', as_of: '2026-10-12', stale_days: 15 }, today);
    expect(f.stale).toBe(false);
    expect(f.text).toMatch(/^Last updated /);
  });
});
