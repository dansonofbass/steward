import { describe, expect, it } from 'vitest';
import { STAMP_LANDS_MS as CELEBRATE_LANDS } from '../../../celebrate/celebrate';
import { leaveFrames, STAMP_LANDS_MS } from './motion';

describe('focus motion', () => {
  it("waits for the celebrate chunk's stamp to land, without importing it", () => {
    expect(STAMP_LANDS_MS).toBe(CELEBRATE_LANDS);
  });
  it('leaves with transform and opacity only: right for a sort, left for Snooze, a drop for Ignore', () => {
    for (const how of ['right', 'left', 'drop'] as const) {
      expect(new Set(leaveFrames(how).flatMap((f) => Object.keys(f)))).toEqual(new Set(['transform', 'opacity']));
    }
    expect(leaveFrames('right')[1].transform).toBe('translateX(120%) rotate(12deg)');
    expect(leaveFrames('left')[1].transform).toBe('translateX(-120%) rotate(-12deg)');
    expect(leaveFrames('drop')[1].transform).toBe('translateY(12px)');
  });
});
