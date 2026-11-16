import { describe, expect, it } from 'vitest';
import { menuPlace } from './menuPlace';

describe('menuPlace (sorting redesign, The picker: under or above, clamped to the viewport)', () => {
  it('opens under the trigger when there is room', () => {
    expect(menuPlace({ left: 100, top: 100, bottom: 140 }, 1280, 800, 0, 0)).toEqual({ left: 100, top: 144, width: 320, height: 380, above: false });
  });

  it('opens above when there is more room there', () => {
    expect(menuPlace({ left: 100, top: 700, bottom: 740 }, 1280, 800, 0, 0)).toEqual({ left: 100, top: 316, width: 320, height: 380, above: true });
  });

  it('stays inside the viewport at the right edge and on a narrow window', () => {
    expect(menuPlace({ left: 1200, top: 100, bottom: 140 }, 1280, 800, 0, 0).left).toBe(944);
    expect(menuPlace({ left: 0, top: 100, bottom: 140 }, 320, 800, 0, 0)).toMatchObject({ left: 16, width: 288 });
  });

  it('takes what room there is, never under 160 px, and adds the scroll so it moves with the page', () => {
    expect(menuPlace({ left: 100, top: 200, bottom: 240 }, 1280, 500, 0, 0)).toMatchObject({ top: 244, height: 240, above: false });
    expect(menuPlace({ left: 100, top: 100, bottom: 140 }, 1280, 220, 0, 0).height).toBe(160);
    expect(menuPlace({ left: 100, top: 100, bottom: 140 }, 1280, 800, 0, 1000).top).toBe(1144);
  });
});
