/** Category moments (sorting redesign, Category moments): small inline SVGs, no image files and no emoji. Each names
 *  the parts that move (class m1, m2, m3) and their keyframes: transform and opacity only, 1.1 s from 80 ms. */
export type Move = { part: string; frames: Keyframe[]; origin?: string };
export type Moment = { svg: string; moves: Move[] };
export const MOMENT_MS = 1100;
export const MOMENT_DELAY_MS = 80;

const svg = (body: string) => '<svg viewBox="0 0 64 64" width="64" height="64" fill="none" stroke="currentColor" '
  + `stroke-width="3" stroke-linecap="round" stroke-linejoin="round">${body}</svg>`;
const across = (from: number, to: number): Keyframe[] => [
  { transform: `translateX(${from}px)`, opacity: 0 }, { transform: 'translateX(0)', opacity: 1, offset: 0.4 },
  { transform: `translateX(${to}px)`, opacity: 0 }];
const drop = (part: string, at: number): Move => ({ part, frames: [
  { transform: 'translateY(-24px)', opacity: 0, offset: 0 }, { transform: 'translateY(-24px)', opacity: 0, offset: at },
  { transform: 'translateY(0)', opacity: 1, offset: at + 0.3 }, { transform: 'translateY(0)', opacity: 1, offset: 1 }] });
const paw = (x: number, y: number) => `<ellipse cx="${x}" cy="${y + 4}" rx="4" ry="3.5"/><circle cx="${x - 4}" cy="${y - 2}" r="1.6"/>`
  + `<circle cx="${x}" cy="${y - 4}" r="1.6"/><circle cx="${x + 4}" cy="${y - 2}" r="1.6"/>`;

export const MOMENTS: Record<string, Moment> = {
  // Getting around: a car zooms across.
  car: { svg: svg('<g class="m1"><path d="M10 40h44v-9l-8-11H22l-8 11z"/><circle cx="21" cy="42" r="5"/><circle cx="43" cy="42" r="5"/></g>'),
    moves: [{ part: 'm1', frames: across(-48, 52) }] },
  // Eating out: steam curls from a bowl.
  bowl: { svg: svg('<path d="M10 34h44a22 22 0 0 1-44 0z"/><g class="m1"><path d="M26 27c-4-4 4-7 0-12M38 27c-4-4 4-7 0-12"/></g>'),
    moves: [{ part: 'm1', frames: [{ transform: 'translateY(6px)', opacity: 0 }, { transform: 'translateY(-2px)', opacity: 1, offset: 0.5 },
      { transform: 'translateY(-10px)', opacity: 0 }] }] },
  // Groceries: an apple drops into a basket.
  apple: { svg: svg('<path d="M12 38h40l-5 15H17z"/><path d="M22 38l6-9M42 38l-6-9"/><g class="m1"><circle cx="32" cy="26" r="7"/><path d="M32 19v-4"/></g>'),
    moves: [{ part: 'm1', frames: [{ transform: 'translateY(-30px)', opacity: 0 }, { transform: 'translateY(0)', opacity: 1, offset: 0.5, easing: 'ease-in' },
      { transform: 'translateY(-4px)', offset: 0.65 }, { transform: 'translateY(6px)', opacity: 1 }] }] },
  // Travel: a paper plane loops away.
  plane: { svg: svg('<g class="m1"><path d="M10 34l44-16-14 30-8-12z"/><path d="M32 36l22-18"/></g>'),
    moves: [{ part: 'm1', frames: [{ transform: 'translate(0, 0) rotate(0deg)', opacity: 1 }, { transform: 'translate(12px, -14px) rotate(-30deg)', offset: 0.35 },
      { transform: 'translate(2px, -28px) rotate(-200deg)', offset: 0.7 }, { transform: 'translate(40px, -40px) rotate(-360deg)', opacity: 0 }] }] },
  // Pets: paw prints trot past.
  paws: { svg: svg(`<g class="m1" fill="currentColor" stroke="none">${paw(16, 40)}${paw(32, 30)}${paw(48, 40)}</g>`),
    moves: [{ part: 'm1', frames: across(-30, 30) }] },
  // Utilities: a bulb flicks on.
  bulb: { svg: svg('<g class="m1" fill="currentColor" stroke="none" opacity="0"><circle cx="32" cy="28" r="12"/></g><path d="M24 40a12 12 0 1 1 16 0v6H24z"/><path d="M26 52h12"/>'),
    moves: [{ part: 'm1', frames: [{ opacity: 0 }, { opacity: 0.6, offset: 0.15 }, { opacity: 0.1, offset: 0.25 }, { opacity: 0.6, offset: 0.4 },
      { opacity: 0.6, offset: 0.85 }, { opacity: 0 }] }] },
  // Gifts: a box pops open.
  gift: { svg: svg('<rect x="14" y="32" width="36" height="22" rx="2"/><path d="M32 32v22"/><g class="m1"><rect x="12" y="25" width="40" height="7" rx="2"/><path d="M32 25c-6-8-14-4-8 0M32 25c6-8 14-4 8 0"/></g>'),
    moves: [{ part: 'm1', origin: '0% 100%', frames: [{ transform: 'translateY(0) rotate(0deg)' }, { transform: 'translateY(-12px) rotate(-14deg)', offset: 0.35 },
      { transform: 'translateY(-10px) rotate(-10deg)' }] }] },
  // Income and Interest: coins stack.
  coins: { svg: svg('<g class="m1"><ellipse cx="32" cy="48" rx="12" ry="4"/></g><g class="m2"><ellipse cx="32" cy="40" rx="12" ry="4"/></g><g class="m3"><ellipse cx="32" cy="32" rx="12" ry="4"/></g>'),
    moves: [drop('m1', 0), drop('m2', 0.2), drop('m3', 0.4)] },
  // Transfer: two arrows swap.
  swap: { svg: svg('<g class="m1"><path d="M14 24h34M42 18l6 6-6 6"/></g><g class="m2"><path d="M50 40H16M22 34l-6 6 6 6"/></g>'),
    moves: [{ part: 'm1', frames: [{ transform: 'translateX(-8px)' }, { transform: 'translateX(8px)' }] },
      { part: 'm2', frames: [{ transform: 'translateX(8px)' }, { transform: 'translateX(-8px)' }] }] },
  // Home and garden: a sprout grows.
  sprout: { svg: svg('<path d="M16 54h32"/><g class="m1"><path d="M32 54V32"/><path d="M32 40c-10 0-14-6-14-12 8 0 14 4 14 12zM32 34c0-8 6-12 14-12 0 8-6 12-14 12z"/></g>'),
    moves: [{ part: 'm1', origin: '50% 100%', frames: [{ transform: 'scale(1, 0)', opacity: 0 }, { transform: 'scale(1, 1)', opacity: 1, offset: 0.6 },
      { transform: 'scale(1, 1)', opacity: 1 }] }] },
  // Health: a heart beats.
  heart: { svg: svg('<g class="m1"><path d="M32 50S12 38 12 25a10 10 0 0 1 20-3 10 10 0 0 1 20 3c0 13-20 25-20 25z"/></g>'),
    moves: [{ part: 'm1', frames: [{ transform: 'scale(1)' }, { transform: 'scale(1.25)', offset: 0.15 }, { transform: 'scale(1)', offset: 0.3 },
      { transform: 'scale(1.2)', offset: 0.45 }, { transform: 'scale(1)', offset: 0.6 }, { transform: 'scale(1)' }] }] },
  // Fun: a balloon floats up.
  balloon: { svg: svg('<g class="m1"><ellipse cx="32" cy="24" rx="11" ry="13"/><path d="M32 37c-2 6 2 10 0 16"/></g>'),
    moves: [{ part: 'm1', frames: [{ transform: 'translateY(14px)', opacity: 0 }, { transform: 'translateY(0)', opacity: 1, offset: 0.3 },
      { transform: 'translateY(-26px)', opacity: 0 }] }] },
  // Every other category: a sparkle.
  sparkle: { svg: svg('<g class="m1"><path d="M32 10l5 17 17 5-17 5-5 17-5-17-17-5 17-5z"/></g>'),
    moves: [{ part: 'm1', frames: [{ transform: 'scale(0) rotate(0deg)', opacity: 0 }, { transform: 'scale(1) rotate(45deg)', opacity: 1, offset: 0.4 },
      { transform: 'scale(0.6) rotate(90deg)', opacity: 0 }] }] },
  // Profile, Kids and college done: a mortarboard tossed and caught.
  mortarboard: { svg: svg('<g class="m1"><path d="M8 26l24-10 24 10-24 10z"/><path d="M18 31v9c8 5 20 5 28 0v-9"/><path d="M52 28v11"/></g>'),
    moves: [{ part: 'm1', origin: '50% 50%', frames: [{ transform: 'translateY(0) rotate(0deg)', opacity: 1 },
      { transform: 'translateY(-26px) rotate(-180deg)', opacity: 1, offset: 0.45, easing: 'ease-out' },
      { transform: 'translateY(0) rotate(-360deg)', opacity: 1, easing: 'ease-in' }] }] },
  // Profile, Home and cars done: a house whose window lights up.
  house: { svg: svg('<path d="M10 30L32 13l22 17"/><path d="M17 25v26h30V25"/><path d="M28 51V40h8v11"/>'
    + '<g class="m1" fill="currentColor" stroke="none" opacity="0"><rect x="38" y="30" width="6" height="6" rx="1"/></g>'),
    moves: [{ part: 'm1', frames: [{ opacity: 0 }, { opacity: 0.85, offset: 0.35 }, { opacity: 0.6, offset: 0.5 }, { opacity: 0.85, offset: 0.65 }, { opacity: 0.85 }] }] },
};

/** The spec's twelve, by category key; Income, Interest and Reimbursement share the coins. */
export const MOMENT_NAMES: Record<string, string> = {
  transport: 'car', dining: 'bowl', groceries: 'apple', travel: 'plane', pets: 'paws', utilities: 'bulb', gifts: 'gift',
  income: 'coins', interest: 'coins', reimbursement: 'coins', transfer: 'swap', home: 'sprout', health: 'heart', entertainment: 'balloon',
};

export const momentFor = (category: string): Moment => MOMENTS[MOMENT_NAMES[category] ?? 'sparkle'];
