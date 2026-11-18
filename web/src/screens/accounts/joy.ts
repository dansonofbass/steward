/** Investment views spec, Joy: what this device has already cheered. A net worth milestone ($100k steps up to $1M, then
 *  $250k steps) and a contribution limit reached cheer once each. The first look records where net worth stands without
 *  a cheer, so the first visit after this ships doesn't celebrate an old crossing (Engineering choice 16). Kept in
 *  localStorage per person and book (issue #6: a second member on a shared device has their own first look), or for
 *  this visit when storage is blocked. Nothing is kept until it is known who is signed in and in which book. Sign-out
 *  calls clearJoy, so the next person on the device can't read the household's net worth bracket. No React,
 *  so lib/signedOut.ts can import it without pulling the Accounts chunk into the first bundle. */
export const MILESTONE_KEY = 'steward-milestone';
export const MAXED_KEY = 'steward-maxed';
const STEP = 100_000_00;
const MILLION = 1_000_000_00;
const BIG_STEP = 250_000_00;

type Seen = { milestone: number | null; maxed: string[] };
let memory = new Map<string, Seen>();

/** The person and book the cheers are kept for, or null until both are known. */
export function joyScope(userId: number | null | undefined, slug: string | null | undefined): string | null {
  return typeof userId === 'number' && slug ? `${userId}:${slug}` : null;
}

/** For tests: forget what this visit remembers. */
export function forgetJoy(): void {
  memory = new Map();
}

/** Sign-out: this visit's memory and every milestone and maxed key on the device, whoever they were kept for, and the
 *  unscoped keys versions before 0.1.1 kept. The theme, swipe and other device settings stay. */
export function clearJoy(): void {
  forgetJoy();
  try {
    const gone: string[] = [];
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k !== null && (k === MILESTONE_KEY || k === MAXED_KEY || k.startsWith(MILESTONE_KEY + ':') || k.startsWith(MAXED_KEY + ':'))) gone.push(k);
    }
    for (const k of gone) localStorage.removeItem(k);
  } catch { /* blocked: nothing was kept */ }
}

function seen(scope: string): Seen {
  let s = memory.get(scope);
  if (!s) {
    s = { milestone: null, maxed: [] };
    memory.set(scope, s);
    try { localStorage.removeItem(MILESTONE_KEY); localStorage.removeItem(MAXED_KEY); } catch { /* blocked */ }
  }
  return s;
}

/** The highest milestone at or below this net worth; 0 below $100k. */
export function milestoneAt(cents: number): number {
  if (cents < STEP) return 0;
  if (cents <= MILLION) return Math.floor(cents / STEP) * STEP;
  return MILLION + Math.floor((cents - MILLION) / BIG_STEP) * BIG_STEP;
}

function keep(scope: string, m: number): void {
  seen(scope).milestone = m;
  try { localStorage.setItem(`${MILESTONE_KEY}:${scope}`, String(m)); } catch { /* blocked: this visit only */ }
}

/** The milestone this net worth just crossed for this person and book on this device, or null. */
export function crossedMilestone(scope: string | null, cents: number): number | null {
  if (scope === null) return null;
  const now = milestoneAt(cents);
  let last = seen(scope).milestone;
  try {
    const raw = localStorage.getItem(`${MILESTONE_KEY}:${scope}`);
    if (raw !== null && Number.isFinite(Number(raw))) last = Number(raw);
  } catch { /* blocked: the memory above */ }
  if (last === null) { keep(scope, now); return null; }
  if (now > last) { keep(scope, now); return now; }
  return null;
}

/** True the first time this person, in this book, sees this limit reached on this device ("{owner}:{kind}:{year}"). */
export function firstMaxed(scope: string | null, key: string): boolean {
  if (scope === null) return false;
  const mine = seen(scope);
  let list = mine.maxed;
  try {
    const raw: unknown = JSON.parse(localStorage.getItem(`${MAXED_KEY}:${scope}`) ?? 'null');
    if (Array.isArray(raw)) list = raw.filter((x): x is string => typeof x === 'string');
  } catch { /* blocked: the memory above */ }
  if (list.includes(key)) return false;
  mine.maxed = [...list, key];
  try { localStorage.setItem(`${MAXED_KEY}:${scope}`, JSON.stringify(mine.maxed)); } catch { /* blocked: this visit only */ }
  return true;
}
