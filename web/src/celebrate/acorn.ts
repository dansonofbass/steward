/** Phase 17 spec 3.1: the acorn companion's motion, here in the celebrate chunk so none of it loads while celebrations
 *  are off or motion is reduced (lib/celebrations.ts withCelebrate). A hop for win, the hop and a sparkle for golden, a
 *  doze with drifting z for resting, one wince-shake for oops, a drop into place for the planting. Each plays once; the doze loops until its stop function
 *  runs (its screen closes). Transform and opacity only, through the Web Animations API, on the drawing's [data-move]
 *  group (ui/Acorn.tsx, ui/OakTree.tsx). Sound: the ding for a win; the wince and the planting never sound. */
import { chime, ding } from './sound';

export type AcornMotion = 'hop' | 'golden' | 'doze' | 'wince' | 'plant';
export const HOP_MS = 900;
export const PLANT_MS = 800;
export const WINCE_MS = 700;
export const DOZE_MS = 3000;
export const SPARKLE_MS = 1400;
export const SPARK_GAP_MS = 250;
const Z_MS = 2400;
const NS = 'http://www.w3.org/2000/svg';
// The sparkle from the golden mockup (acorn-golden-v2), around the 32 grid.
const SPARKS = [
  'M2 7l1 2 2 1-2 1-1 2-1-2-2-1 2-1z',
  'M29 17l.8 1.6 1.6.8-1.6.8-.8 1.6-.8-1.6-1.6-.8 1.6-.8z',
  'M26 1l.6 1.2 1.2.6-1.2.6-.6 1.2-.6-1.2-1.2-.6 1.2-.6z',
];
const HOP: Keyframe[] = [
  { transform: 'translateY(0)' },
  { transform: 'translateY(-12px) rotate(-6deg)', offset: 0.33 },
  { transform: 'translateY(0) rotate(4deg)', offset: 0.66 },
  { transform: 'translateY(0)' },
];
const WINCE: Keyframe[] = [
  { transform: 'translateX(0) rotate(0)' },
  { transform: 'translateX(-2px) rotate(-5deg)', offset: 0.15 },
  { transform: 'translateX(2px) rotate(5deg)', offset: 0.3 },
  { transform: 'translateX(-1.5px) rotate(-3deg)', offset: 0.45 },
  { transform: 'translateX(1px) rotate(2deg)', offset: 0.6 },
  { transform: 'translateX(0) rotate(0)' },
];
const PLANT: Keyframe[] = [{ transform: 'translateY(-24px)' }, { transform: 'translateY(0)' }];   // dropped into the ground
const DOZE: Keyframe[] = [{ transform: 'rotate(-14deg)' }, { transform: 'rotate(-10deg)' }, { transform: 'rotate(-14deg)' }];
const TWINKLE: Keyframe[] = [{ opacity: 0, transform: 'scale(0.4)' }, { opacity: 1, transform: 'scale(1)' }, { opacity: 0, transform: 'scale(0.4)' }];
const DRIFT: Keyframe[] = [{ opacity: 0, transform: 'translate(0, 0)' }, { opacity: 1, offset: 0.3 }, { opacity: 0, transform: 'translate(10px, -16px)' }];

function play(el: Element, frames: Keyframe[], opts: KeyframeAnimationOptions): Animation | null {
  const a = (el as Element & { animate?: (f: Keyframe[], o: KeyframeAnimationOptions) => Animation }).animate;
  return typeof a === 'function' ? a.call(el, frames, opts) : null;
}

function part(svg: SVGSVGElement, tag: 'path' | 'text', cls: string): SVGElement {
  const el = document.createElementNS(NS, tag) as SVGElement;
  el.setAttribute('class', cls);
  el.setAttribute('aria-hidden', 'true');
  svg.appendChild(el);
  return el;
}

export function acorn({ svg, motion, sound = false }: { svg: SVGSVGElement; motion: AcornMotion; sound?: boolean }): () => void {
  const body = svg.querySelector<SVGGElement>('[data-move]') ?? svg;
  body.style.transformOrigin = motion === 'doze' ? '50% 95%' : '50% 90%';
  const anims: (Animation | null)[] = [];
  const extras: SVGElement[] = [];
  let timer = 0;
  if (motion === 'hop' || motion === 'golden') anims.push(play(body, HOP, { duration: HOP_MS, easing: 'cubic-bezier(.2, .7, .2, 1)' }));
  if (motion === 'wince') anims.push(play(body, WINCE, { duration: WINCE_MS, easing: 'ease-in-out' }));
  if (motion === 'plant') anims.push(play(body, PLANT, { duration: PLANT_MS, easing: 'cubic-bezier(.2,.8,.3,1)' }));
  if (motion === 'golden') {
    SPARKS.forEach((d, i) => {
      const p = part(svg, 'path', 'acorn__spark');
      p.setAttribute('d', d);
      extras.push(p);
      anims.push(play(p, TWINKLE, { duration: SPARKLE_MS, delay: i * SPARK_GAP_MS, fill: 'both' }));
    });
    timer = window.setTimeout(() => { for (const e of extras) e.remove(); }, SPARKLE_MS + 2 * SPARK_GAP_MS + 50);
  }
  if (motion === 'doze') {
    anims.push(play(body, DOZE, { duration: DOZE_MS, iterations: Infinity, easing: 'ease-in-out' }));
    [[24, 10], [26, 6]].forEach(([x, y], i) => {
      const z = part(svg, 'text', 'acorn__z');
      z.setAttribute('x', String(x));
      z.setAttribute('y', String(y));
      z.textContent = 'z';
      extras.push(z);
      anims.push(play(z, DRIFT, { duration: Z_MS, delay: i * (Z_MS / 2), iterations: Infinity, fill: 'both' }));
    });
  }
  if (sound && motion !== 'wince' && motion !== 'plant') (motion === 'golden' ? chime : ding)();
  return () => {
    window.clearTimeout(timer);
    for (const a of anims) a?.cancel();
    for (const e of extras) e.remove();
  };
}
