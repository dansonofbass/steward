/** The celebrate chunk (sorting redesign, Celebrations): loaded with import() on the first celebration of a visit,
 *  and nothing in it runs unless celebrations are on (lib/celebrations.ts withCelebrate). It imports only lib/copy and lib/sky (both in
 *  the main bundle) and its own files, and stays within 12 KB gzip (scripts/bundle-size.mjs). DOM motion goes through
 *  the Web Animations API on transform and opacity; streamers, sparks and the sunrise share engine.ts's one canvas. */
import { STAMP_LATER, STAMP_OK, STAMP_SORTED } from '../lib/copy';
import { SPARKS_MAX, sparks, STREAMER_DELAY, streamers, sunrise as glow } from './effects';
import { engine } from './engine';
import { MOMENT_DELAY_MS, MOMENT_MS, MOMENTS, momentFor, type Moment } from './moments';
import { look } from './season';
import { isDarkPhase } from '../lib/sky';
import { ding } from './sound';
import './celebrate.css';

export { acorn } from './acorn';
export type { AcornMotion } from './acorn';

// Paced so the receipt reads before anything competes with it (each effect still ends within 1.6 s of its own start):
// the receipt and its cheer at 0 ms; the stamp from 280 ms, about 450 ms, with the tick and the ding as it lands; the
// burst as the stamp settles (streamers and the category moment 80 ms into it, at 730 ms); the sparks last (300 ms
// into the burst, at 950 ms).
export const STAMP_DELAY_MS = 280;
export const STAMP_MS = 450;
export const STAMP_LANDS_MS = STAMP_DELAY_MS + Math.round(STAMP_MS * 0.55);
export const BURST_MS = STAMP_DELAY_MS + STAMP_MS - Math.round(STREAMER_DELAY * 1000);
export const POP_MS = 1200;

const token = (name: string, fallback: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
/** A dark sky phase on screen: the season's dark palette (phase 17, spec 2.5). */
const dark = () => isDarkPhase(document.documentElement.dataset.phase);
/** The plain streamers: the plum that reads in every phase, the green, gold and coral. */
const streamerBase = () => [token('--accent-text', '#7C3352'), token('--money-in', '#789B80'), '#E8B04B', '#E07A5F'];

function play(el: Element, frames: Keyframe[], opts: KeyframeAnimationOptions): Animation | null {
  return typeof (el as HTMLElement).animate === 'function' ? (el as HTMLElement).animate(frames, opts) : null;
}

const removeAfter = (el: Element, ms: number) => { window.setTimeout(() => { el.remove(); }, ms); };

// Issue #14: the page's CSP requires Trusted Types, so markup reaches innerHTML only through this one named policy
// (TRUSTED_TYPES_POLICY in steward/api/headers.py), and the policy lets through only the moments' own fixed SVG.
type HtmlPolicy = { createHTML: (markup: string) => unknown };
type TrustedTypes = { createPolicy: (name: string, rules: { createHTML: (markup: string) => string }) => HtmlPolicy };
const FIXED = new Set(Object.values(MOMENTS).map((m) => m.svg));
const onlyFixed = (markup: string) => {
  if (!FIXED.has(markup)) throw new TypeError('Not a celebration moment.');
  return markup;
};
let policy: HtmlPolicy | null | undefined;

function fixedMarkup(markup: string): string {
  if (policy === undefined) {
    const tt = (window as unknown as { trustedTypes?: TrustedTypes }).trustedTypes;
    policy = tt ? tt.createPolicy('celebrate', { createHTML: onlyFixed }) : null;   // once a page: the name is unique
  }
  // A TrustedHTML where the browser has Trusted Types; innerHTML takes it as it takes a string.
  return (policy ? policy.createHTML(markup) : onlyFixed(markup)) as string;
}

/** The rubber stamp thunks onto the receipt with a two-frame shake, about 450 ms from STAMP_DELAY_MS, and stays there.
 *  `host` is the receipt's place for it beside the cheer (the card itself only as a fallback). */
function stamp(host: HTMLElement, text: string): HTMLElement {
  const s = document.createElement('span');
  s.className = 'cel-stamp';
  s.textContent = text;
  s.setAttribute('aria-hidden', 'true');
  host.appendChild(s);
  s.style.willChange = 'transform, opacity';
  const a = play(s, [
    { transform: 'rotate(-12deg) scale(1.5)', opacity: 0 },
    { transform: 'rotate(-12deg) scale(1)', opacity: 1, offset: 0.55 },
    { transform: 'rotate(-12deg) translate(2px, 1px)', offset: 0.7 },
    { transform: 'rotate(-12deg) translate(-2px, -1px)', offset: 0.85 },
    { transform: 'rotate(-12deg)', opacity: 1 },
  ], { duration: STAMP_MS, delay: STAMP_DELAY_MS, fill: 'backwards', easing: 'cubic-bezier(.2, .7, .2, 1)' });
  const done = () => { s.style.willChange = ''; };
  if (a) void a.finished.then(done, done); else done();
  return s;
}

function moment(card: HTMLElement, m: Moment): HTMLElement {
  const host = document.createElement('span');
  host.className = 'cel-moment';
  host.setAttribute('aria-hidden', 'true');
  host.innerHTML = fixedMarkup(m.svg);         // fixed markup from moments.ts, never data
  card.appendChild(host);
  for (const mv of m.moves) {
    const part = host.querySelector<SVGGElement>(`.${mv.part}`);
    if (!part) continue;
    if (mv.origin) part.style.transformOrigin = mv.origin;
    play(part, mv.frames, { duration: MOMENT_MS, delay: MOMENT_DELAY_MS, easing: 'ease-out', fill: 'both' });
  }
  removeAfter(host, MOMENT_DELAY_MS + MOMENT_MS + 50);
  return host;
}

/** `stamp`: a place for the stamp (else the card). `mark: false`: no stamp at all (the list's slim row carries its own
 *  SORTED tag). `tick: false`: no landing tick (a swipe already ticked at its threshold, review focus P33). */
export type SortCelebration = {
  card: HTMLElement; stamp?: HTMLElement | null; category: string; applied: number; sound: boolean; mark?: boolean; tick?: boolean; now?: Date;
};

/** A sort, in the order above: the stamp, then the tick and the ding as it lands, then the burst (streamers and the
 *  category moment, then a spark per matching row). Returns a function that takes it all off again (Undo), including
 *  whatever has not started yet. */
export function sorted({ card, stamp: at = null, category, applied, sound, mark = true, tick = true, now = new Date() }: SortCelebration): () => void {
  const s = mark ? stamp(at ?? card, STAMP_SORTED) : null;
  let m: HTMLElement | null = null;
  const timers = [
    window.setTimeout(() => {
      if (tick) navigator.vibrate?.(12);
      if (sound) ding();
    }, STAMP_LANDS_MS),
    window.setTimeout(() => {
      if (!card.isConnected) return;
      const box = card.getBoundingClientRect();
      const green = token('--money-in', '#789B80');
      const n = Math.min(Math.max(0, applied), SPARKS_MAX);
      engine.add([...streamers(box, look(now, streamerBase(), dark()), Math.max(0, engine.capacity() - n)), ...sparks(box, n, green)]);
      m = moment(card, momentFor(category));
    }, BURST_MS),
  ];
  return () => {
    for (const t of timers) window.clearTimeout(t);
    s?.remove();
    m?.remove();
  };
}

/** Snooze and Ignore play only the stamp (LATER or OK) and, later, the file-away. */
export function quiet({ card, stamp: at = null, kind }: { card: HTMLElement; stamp?: HTMLElement | null; kind: 'snooze' | 'ignore' }): () => void {
  const s = stamp(at ?? card, kind === 'snooze' ? STAMP_LATER : STAMP_OK);
  return () => { s.remove(); };
}

/** Reimbursable spec, Joy: a payer's balance reached $0 ("All square with Acme."). Streamers and the Income coins
 *  moment over `host`, no stamp and no tick. */
export function square({ host }: { host: HTMLElement }): () => void {
  engine.add(streamers(host.getBoundingClientRect(), look(new Date(), streamerBase(), dark()), engine.capacity()));
  const m = moment(host, momentFor('income'));
  return () => { m.remove(); };
}

/** Marking a trip: the Travel moment (the plane), once. */
export function trip({ host }: { host: HTMLElement }): () => void {
  const m = moment(host, momentFor('travel'));
  return () => { m.remove(); };
}

/** Ten in a row or a milestone pops over the queue, and is said to screen readers. */
export function pop(text: string): void {
  const el = document.createElement('div');
  el.className = 'cel-pop';
  el.setAttribute('role', 'status');
  el.textContent = text;
  document.body.appendChild(el);
  play(el, [
    { transform: 'translate(-50%, 12px) scale(0.8)', opacity: 0 },
    { transform: 'translate(-50%, 0) scale(1.05)', opacity: 1, offset: 0.2 },
    { transform: 'translate(-50%, 0) scale(1)', opacity: 1, offset: 0.75 },
    { transform: 'translate(-50%, -8px) scale(1)', opacity: 0 },
  ], { duration: POP_MS, easing: 'ease-out', fill: 'forwards' });
  removeAfter(el, POP_MS + 50);
}

/** The sunrise over "All caught up!", once per visit (Review decides), about 1.6 s on the shared canvas. */
export function sunrise(over: HTMLElement): void {
  engine.addDrawer(glow(over.getBoundingClientRect(), [token('--money-in', '#789B80'), '#E8B04B']));
}

export const CLOSER_STREAMERS = 16;

/** The Plan's change line when the Comfortably age moved earlier (plan subpages decision 7): a small burst of streamers
 *  from the line, on the shared canvas. No stamp, tick or ding: nothing was sorted. */
export function closer({ over, now = new Date() }: { over: HTMLElement; now?: Date }): void {
  engine.add(streamers(over.getBoundingClientRect(), look(now, streamerBase(), dark()), Math.min(CLOSER_STREAMERS, engine.capacity())));
}

/** Investment views spec, Joy: a net worth milestone, a contribution limit reached, or the first look at what an account
 *  holds. The same small burst as the Plan's change line, from `over`; no stamp, tick or ding. */
export function burst({ over, now = new Date() }: { over: HTMLElement; now?: Date }): void {
  closer({ over, now });
}

/** Profile spec P28: the section's moment over `host` (Kids and college, the mortarboard; Home and cars, the lit
 *  window), or for 5 of 5 a short line of confetti. No stamp, tick or ding: nothing was sorted. */
export function profile({ host, kind, now = new Date() }: { host: HTMLElement; kind: 'kids' | 'home' | 'all'; now?: Date }): () => void {
  if (kind === 'all') {
    closer({ over: host, now });
    return () => {};
  }
  const m = moment(host, MOMENTS[kind === 'kids' ? 'mortarboard' : 'house']);
  m.classList.add('cel-moment--row');
  return () => { m.remove(); };
}

/** Phase 17 spec 3.7: a win's small moment over `host` (payday and an import, the coins; a set-aside covered early, the
 *  sprout), and the ding when Sound is on. No stamp, streamers or tick. Returns a function that takes it off again. */
export function winMoment({ host, name, sound = false }: { host: HTMLElement; name: 'coins' | 'sprout'; sound?: boolean }): () => void {
  const m = moment(host, MOMENTS[name]);
  if (sound) ding();
  return () => { m.remove(); };
}
