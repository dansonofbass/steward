/** Review focus, Data (P1, P2, P13): the view per person on this device, Swipe to sort and the swipe demo per device.
 *  Every access is wrapped, as lib/celebrations.ts does. With no storage: focus, swipes on, and the nudge at most once
 *  per page load (a module flag). */
export type ReviewView = 'focus' | 'list';
export type DemoState = 'nudged' | 'done' | null;

const VIEW = 'steward-review-view:';
const SWIPE = 'steward-swipe';
const DEMO = 'steward-swipe-demo';
let nudgedThisLoad = false;

export function readView(userId: number | null): ReviewView {
  if (userId === null) return 'focus';
  try { return localStorage.getItem(VIEW + userId) === 'list' ? 'list' : 'focus'; } catch { return 'focus'; }
}

export function saveView(userId: number | null, v: ReviewView): void {
  if (userId === null) return;
  try { localStorage.setItem(VIEW + userId, v); } catch { /* private mode: this visit only */ }
}

export function swipeOn(): boolean {
  try { return localStorage.getItem(SWIPE) !== 'off'; } catch { return true; }
}

export function setSwipe(on: boolean): void {
  try {
    if (on) localStorage.removeItem(SWIPE);
    else localStorage.setItem(SWIPE, 'off');
  } catch { /* private mode */ }
}

export function demoState(): DemoState {
  try {
    const v = localStorage.getItem(DEMO);
    return v === 'nudged' || v === 'done' ? v : null;
  } catch { return nudgedThisLoad ? 'nudged' : null; }
}

/** `nudged` when the demo has played; `done` at the first sort in focus. Done is never turned back into nudged. */
export function setDemo(s: 'nudged' | 'done'): void {
  nudgedThisLoad = true;
  try {
    if (s === 'nudged' && localStorage.getItem(DEMO) === 'done') return;
    localStorage.setItem(DEMO, s);
  } catch { /* private mode: the module flag holds it for this page load */ }
}

/** Replay the swipe demo (Appearance): the nudge and the hint both come back. */
export function clearDemo(): void {
  nudgedThisLoad = false;
  try { localStorage.removeItem(DEMO); } catch { /* private mode */ }
}

/** Tests only (test-setup.ts): the page-load flag starts clear in every test. */
export function forgetDemoLoad(): void { nudgedThisLoad = false; }
