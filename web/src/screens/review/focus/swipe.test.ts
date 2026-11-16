import { describe, expect, it } from 'vitest';
import { commits, crossed, labelStyle, lockOf, progress, rotation, type Sample } from './swipe';

const W = { width: 1000, height: 1000 };      // the 120 px caps decide
const N = { width: 300, height: 360 };        // 30% (90 px) and 25% (90 px) decide
const slow: Sample[] = [{ x: 0, y: 0, t: 0 }, { x: 1, y: 0, t: 400 }];

describe('swipe thresholds (review focus, Gestures P9)', () => {
  it('waits for 8 px of travel, then locks to the larger axis; a downward lock does nothing', () => {
    expect(lockOf(7, 0)).toBeNull();
    expect(lockOf(0, -7)).toBeNull();
    expect(lockOf(8, 3)).toBe('x');
    expect(lockOf(-8, 8)).toBe('x');                // a tie is horizontal
    expect(lockOf(3, -9)).toBe('y');
    expect(lockOf(3, 9)).toBe('down');
    expect(progress('down', 0, 200, W)).toEqual({ dir: null, p: 0 });
    expect(commits('down', 0, 200, W, slow)).toBeNull();
  });

  it('commits left or right at min(30% of the width, 120 px)', () => {
    expect(commits('x', 119, 0, W, slow)).toBeNull();
    expect(commits('x', 120, 0, W, slow)).toBe('right');
    expect(commits('x', -120, 0, W, slow)).toBe('left');
    expect(commits('x', 89.7, 0, N, slow)).toBeNull();      // 29.9%
    expect(commits('x', 90, 0, N, slow)).toBe('right');      // 30%
  });

  it('commits up at min(25% of the height, 120 px)', () => {
    expect(commits('y', 0, -119, W, slow)).toBeNull();
    expect(commits('y', 0, -120, W, slow)).toBe('up');
    expect(commits('y', 0, -90, N, slow)).toBe('up');
  });

  it('or on a flick: 0.6 px/ms over the last 80 ms, with at least 48 px of travel', () => {
    const flick = (v: number, at = 0): Sample[] => [{ x: at, y: 0, t: 0 }, { x: at, y: 0, t: 100 }, { x: at + v * 80, y: 0, t: 180 }];
    expect(commits('x', 60, 0, W, flick(0.6, 12))).toBe('right');
    expect(commits('x', 60, 0, W, flick(0.59, 12))).toBeNull();
    expect(commits('x', 47, 0, W, flick(0.6, 0))).toBeNull();          // a flick under 48 px
    expect(commits('x', -60, 0, W, flick(0.6, -60))).toBeNull();       // a flick back the other way
    const up: Sample[] = [{ x: 0, y: 0, t: 0 }, { x: 0, y: -50, t: 80 }];
    expect(commits('y', 0, -50, W, up)).toBe('up');
  });

  it('grows the label to the threshold, then holds; rotates up to 8° unless motion is reduced', () => {
    expect(progress('x', 60, 0, W)).toEqual({ dir: 'right', p: 0.5 });
    expect(labelStyle(0)).toEqual({ opacity: 0, scale: 0.8 });
    expect(labelStyle(0.5)).toEqual({ opacity: 0.5, scale: 0.975 });
    expect(labelStyle(1)).toEqual({ opacity: 1, scale: 1.15 });
    expect(labelStyle(3)).toEqual({ opacity: 1, scale: 1.15 });
    expect(rotation(250, 1000, false)).toBe(2);
    expect(rotation(5000, 1000, false)).toBe(8);
    expect(rotation(-5000, 1000, false)).toBe(-8);
    expect(rotation(250, 1000, true)).toBe(0);
  });

  it('ticks once on entering the zone, and again only after leaving it', () => {
    expect(crossed(false, 0.99)).toEqual({ inZone: false, tick: false });
    expect(crossed(false, 1)).toEqual({ inZone: true, tick: true });
    expect(crossed(true, 1.4)).toEqual({ inZone: true, tick: false });
    expect(crossed(true, 0.5)).toEqual({ inZone: false, tick: false });
    expect(crossed(false, 1.1)).toEqual({ inZone: true, tick: true });
  });
});
