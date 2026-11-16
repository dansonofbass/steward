/** Investment views spec, Joy: what this device has already cheered. A net worth milestone ($100k steps up to $1M, then
 *  $250k steps) and a contribution limit reached cheer once each. The first look records where net worth stands without
 *  a cheer, so the first visit after this ships doesn't celebrate an old crossing (Engineering choice 16). Kept in
 *  localStorage, or for this visit when storage is blocked. */
export const MILESTONE_KEY = 'steward-milestone';
export const MAXED_KEY = 'steward-maxed';
const STEP = 100_000_00;
const MILLION = 1_000_000_00;
const BIG_STEP = 250_000_00;

let memory: { milestone: number | null; maxed: string[] } = { milestone: null, maxed: [] };

/** For tests: forget what this visit remembers. */
export function forgetJoy(): void {
  memory = { milestone: null, maxed: [] };
}

/** The highest milestone at or below this net worth; 0 below $100k. */
export function milestoneAt(cents: number): number {
  if (cents < STEP) return 0;
  if (cents <= MILLION) return Math.floor(cents / STEP) * STEP;
  return MILLION + Math.floor((cents - MILLION) / BIG_STEP) * BIG_STEP;
}

function keep(m: number): void {
  memory.milestone = m;
  try { localStorage.setItem(MILESTONE_KEY, String(m)); } catch { /* blocked: this visit only */ }
}

/** The milestone this net worth just crossed on this device, or null. */
export function crossedMilestone(cents: number): number | null {
  const now = milestoneAt(cents);
  let seen = memory.milestone;
  try {
    const raw = localStorage.getItem(MILESTONE_KEY);
    if (raw !== null && Number.isFinite(Number(raw))) seen = Number(raw);
  } catch { /* blocked: the memory above */ }
  if (seen === null) { keep(now); return null; }
  if (now > seen) { keep(now); return now; }
  return null;
}

/** True the first time this device sees this limit reached ("{owner}:{kind}:{year}"). */
export function firstMaxed(key: string): boolean {
  let seen = memory.maxed;
  try {
    const raw: unknown = JSON.parse(localStorage.getItem(MAXED_KEY) ?? 'null');
    if (Array.isArray(raw)) seen = raw.filter((x): x is string => typeof x === 'string');
  } catch { /* blocked: the memory above */ }
  if (seen.includes(key)) return false;
  memory.maxed = [...seen, key];
  try { localStorage.setItem(MAXED_KEY, JSON.stringify(memory.maxed)); } catch { /* blocked: this visit only */ }
  return true;
}
