import { render } from '@testing-library/react';
import { createElement } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest';
import { useFakeTimers } from '../test-clock';
import { Acorn } from '../ui/Acorn';

const fx = vi.hoisted(() => ({ ding: vi.fn(), chime: vi.fn() }));
vi.mock('./sound', () => ({ ding: fx.ding, chime: fx.chime }));

import { acorn, HOP_MS, PLANT_MS, SPARK_GAP_MS, SPARKLE_MS } from './acorn';

type Played = { el: Element; frames: Keyframe[]; opts: KeyframeAnimationOptions; cancel: Mock };
let played: Played[];
beforeEach(() => {
  played = [];
  (Element.prototype as unknown as { animate: unknown }).animate = vi.fn(function (this: Element, frames: Keyframe[], opts: KeyframeAnimationOptions) {
    const a = { el: this, frames, opts, cancel: vi.fn() };
    played.push(a);
    return a as unknown as Animation;
  });
});
afterEach(() => { delete (Element.prototype as unknown as { animate?: unknown }).animate; vi.clearAllMocks(); });
const drawn = (face: 'win' | 'golden' | 'resting' | 'oops' = 'win') =>
  render(createElement(Acorn, { face, season: null })).container.querySelector<SVGSVGElement>('svg')!;

describe("the acorn's motion (phase 17 spec 3.1), in the celebrate chunk", () => {
  it('a hop plays once on the drawing, with the ding only when Sound is on', () => {
    const svg = drawn();
    acorn({ svg, motion: 'hop' });
    expect(played).toHaveLength(1);
    expect(played[0].el).toBe(svg.querySelector('[data-move]'));
    expect(played[0].opts).toMatchObject({ duration: HOP_MS });
    expect(played[0].opts.iterations).toBeUndefined();
    expect(fx.ding).not.toHaveBeenCalled();
    acorn({ svg, motion: 'hop', sound: true });
    expect(fx.ding).toHaveBeenCalledOnce();
  });

  it('the planting drops the acorn into place once, over PLANT_MS, and plays no sound even with Sound on', () => {
    const svg = drawn();
    acorn({ svg, motion: 'plant', sound: true });
    expect(played).toHaveLength(1);
    expect(played[0].el).toBe(svg.querySelector('[data-move]'));
    expect(played[0].frames).toEqual([{ transform: 'translateY(-24px)' }, { transform: 'translateY(0)' }]);
    expect(played[0].opts).toMatchObject({ duration: PLANT_MS });
    expect(played[0].opts.iterations).toBeUndefined();
    expect(played[0].opts.fill).toBeUndefined();            // it ends at rest, not held
    expect([fx.ding.mock.calls.length, fx.chime.mock.calls.length]).toEqual([0, 0]);
  });

  it('the golden one hops and sparkles three times, and the sparks leave when they are done', () => {
    useFakeTimers();
    const svg = drawn('golden');
    acorn({ svg, motion: 'golden' });
    expect(svg.querySelectorAll('.acorn__spark')).toHaveLength(3);
    expect(played).toHaveLength(4);
    vi.advanceTimersByTime(SPARKLE_MS + 2 * SPARK_GAP_MS + 50);
    expect(svg.querySelectorAll('.acorn__spark')).toHaveLength(0);
  });

  it('the doze loops with two drifting z until it is stopped, and then leaves nothing behind', () => {
    const svg = drawn('resting');
    const stop = acorn({ svg, motion: 'doze' });
    expect(svg.querySelectorAll('.acorn__z')).toHaveLength(2);
    expect(played.every((p) => p.opts.iterations === Infinity)).toBe(true);
    stop();
    expect(svg.querySelectorAll('.acorn__z')).toHaveLength(0);
    expect(played.every((p) => p.cancel.mock.calls.length === 1)).toBe(true);
  });

  it('the wince plays once and never makes a sound, even with Sound on', () => {
    const svg = drawn('oops');
    acorn({ svg, motion: 'wince', sound: true });
    expect(played).toHaveLength(1);
    expect(played[0].opts.iterations).toBeUndefined();
    expect(fx.ding).not.toHaveBeenCalled();
  });

  it('the golden moment plays the chime, not the ding; the wince plays neither', () => {
    acorn({ svg: drawn('golden'), motion: 'golden', sound: true });
    expect([fx.chime.mock.calls.length, fx.ding.mock.calls.length]).toEqual([1, 0]);
    acorn({ svg: drawn('oops'), motion: 'wince', sound: true });
    expect([fx.chime.mock.calls.length, fx.ding.mock.calls.length]).toEqual([1, 0]);
  });

  it('without the Web Animations API nothing throws and nothing is left behind', () => {
    delete (Element.prototype as unknown as { animate?: unknown }).animate;
    const svg = drawn('resting');
    const stop = acorn({ svg, motion: 'doze' });
    stop();
    expect(svg.querySelectorAll('.acorn__z')).toHaveLength(0);
  });
});
