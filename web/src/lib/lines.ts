/** Phase 17 spec 3.2: every moment's line pool in one place, so the copy can be read and edited together. Grown from the
 *  sort cheers (sorting redesign, Cheers): a shuffled bag per pool, kept on this device, so no line repeats until every
 *  one has been said, and never the same line twice in a row, across bags too. Lines are copy, not motion: they show
 *  whether celebrations are on or off. Only lazy chunks import this file (scripts/bundle-size.mjs checks). */

export type Pool =
  | 'sort' | 'big' | 'gentle' | 'reimbursement'
  | 'caughtUp' | 'importDone' | 'payday' | 'setAsideCovered' | 'setAsideFirst' | 'profileDone' | 'planChecklistDone'
  | 'gatewayBack' | 'goldenSort'
  | 'setupStep' | 'planted' | 'ready';

export const POOLS: Record<Pool, readonly string[]> = {
  sort: [
    'Boom! Another one bites the dust.',
    'Sorted. Your future self says thanks.',
    'Swish. Nothing but net.',
    'Case closed.',
    'The ledger thanks you.',
    'Neat and tidy.',
    'One more in its place.',
    'Filed with care.',
    'Look at you go.',
    'Crisp.',
    'Right where it belongs.',
    'Nicely done.',
    'Tidy books, calm mind.',
    "And that's that.",
    'Smooth.',
    'Another one off the pile.',
    'Done and dusted.',
    'Order restored.',
    'Your books are glowing.',
    'Easy does it.',
    'Clean as a whistle.',
    'Sorted with style.',
    "That's a keeper.",
    'Bit by bit, it all adds up.',
    'The numbers feel lighter already.',
    'One less thing to think about.',
    'Steady hands.',
    "Chef's kiss.",
    'Nailed it.',
    'Exactly right.',
  ],
  // When the sort also set 3 or more matching rows.
  big: [
    "Now that's a clean sweep.",
    'A whole stack, sorted in one go.',
    'One tap, a whole row of tidy.',
    'Look at all that order.',
    'That cleared a path.',
    'Big sort energy.',
    'Lots done in one tap.',
    'The pile just got a lot smaller.',
  ],
  // Snooze and Ignore.
  gentle: ['Fair enough.', 'No rush.', 'Noted.', 'All right, moving on.', 'Got it.', 'Your call, and a fine one.'],
  // A repayment (reimbursable spec, Joy): {payer} is the reimburser record's name, filled by payerCheer.
  reimbursement: [
    'Money back in your pocket.',
    '{payer} paid up.',
    'The check cleared. Metaphorically.',
    '{payer} came through.',
    'Your money found its way home.',
    'One step closer to even with {payer}.',
    'That trip just got a little lighter.',
    'Nice. That one is yours again.',
  ],
  caughtUp: ['Nothing to sort. The books are tidy.', 'All caught up. Go do something fun.', "Every one sorted. Steward's got the rest.", 'Clean slate.'],
  // R3: {rows} is "1 row" or "143 rows", {waiting} is "1 waits" or "12 wait"; chosen by whether any wait
  // (importDoneLine), not drawn.
  importDone: ['{rows} in. {waiting} in Review.', '{rows} in, and nothing to sort.'],
  payday: ['Payday came.', 'Payday came. Nicely done.'],
  setAsideCovered: ['{name} is covered, with {weeks} to spare.'],
  setAsideFirst: ["{month} won't sting this year."],
  profileDone: ['All five. The plan has what it needs.'],
  // R2: no count, so it reads right with 6 required items or 7 (with a mortgage).
  planChecklistDone: ['Every box ticked. The plan can see you now.'],
  gatewayBack: ['{gateway} is back. Catching up.'],
  goldenSort: ['A golden acorn. Rare find.', 'That one sparkled.', 'One in forty. Lucky you.'],
  // Guided setup (spec 9): a first-run step done, the acorn planted, and Get Steward ready at nothing left.
  setupStep: ['One down.', "That's in.", 'Nice. Next one.'],
  planted: ['It grows as your books do.'],
  ready: ['Nothing needs you.'],
};

const KEY = 'steward-cheers';          // the sort cheers' old bags carry on
type Bags = Partial<Record<string, number[]>>;
let memory: Bags = {};                  // when storage is blocked: this visit only
/** For tests: forget what this visit remembers when storage is blocked. */
export function forgetLines(): void { memory = {}; }

function read(): Bags {
  try {
    const raw: unknown = JSON.parse(localStorage.getItem(KEY) ?? '{}');
    return raw && typeof raw === 'object' ? (raw as Bags) : {};
  } catch {
    return memory;
  }
}

function write(b: Bags): void {
  memory = b;
  try { localStorage.setItem(KEY, JSON.stringify(b)); } catch { /* private mode: this visit only */ }
}

function shuffled(n: number, rnd: () => number): number[] {
  const a = Array.from({ length: n }, (_, i) => i);
  for (let i = n - 1; i > 0; i--) {
    const j = Math.floor(rnd() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

/** The no-repeat bag for any list of lines, kept on this device under `bag`. A new bag never starts with the line the
 *  last one ended on. The Plan's change line keeps its own lines in its chunk and draws them here. */
export function drawFrom(bag: string, lines: readonly string[], rnd: () => number = Math.random): string {
  const bags = read();
  const n = lines.length;
  const valid = (i: unknown): i is number => Number.isInteger(i) && (i as number) >= 0 && (i as number) < n;
  const lastKey = `${bag}:last`;
  const prev = (Array.isArray(bags[lastKey]) ? bags[lastKey] : [])[0];
  let left = (Array.isArray(bags[bag]) ? bags[bag] : []).filter(valid);
  if (left.length === 0) {
    left = shuffled(n, rnd);
    if (n > 1 && left[0] === prev) [left[0], left[1]] = [left[1], left[0]];
  }
  const [i, ...rest] = left;
  write({ ...bags, [bag]: rest, [lastKey]: [i] });
  return lines[i];
}

/** {name}-style values into a line; a name with no value stays as written. */
export function fill(line: string, vars: Record<string, string | number> = {}): string {
  return line.replace(/\{(\w+)\}/g, (all, k: string) => (k in vars ? String(vars[k]) : all));
}

export function nextLine(pool: Pool, vars: Record<string, string | number> = {}, rnd: () => number = Math.random): string {
  return fill(drawFrom(pool, POOLS[pool], rnd), vars);
}

/** A repayment's cheer, with the payer's name from the reimburser record where it reads naturally. */
export const payerCheer = (payer: string, rnd: () => number = Math.random): string => nextLine('reimbursement', { payer }, rnd);

const n0 = (n: number) => n.toLocaleString('en-US');
/** Spec 3.7, ruling R3: every commit's receipt line, singular for one ("1 row in. 1 waits in Review."). */
export const importDoneLine = (n: number, m: number): string =>
  fill(POOLS.importDone[m > 0 ? 0 : 1], {
    rows: n === 1 ? '1 row' : `${n0(n)} rows`,
    waiting: m === 1 ? '1 waits' : `${n0(m)} wait`,
  });

/** A set-aside's time to spare: whole weeks from two weeks, a week from seven days, else days. */
export function spareWeeks(days: number): string {
  if (days >= 14) return `${Math.floor(days / 7)} weeks`;
  if (days >= 7) return 'a week';
  return days === 1 ? 'a day' : `${days} days`;
}

// ---- Rare surprises (spec 3.3) ----

export const GOLDEN_ODDS = 1 / 40;
/** About 1 in 40. Rolled on the device; nothing is stored. */
export const rollGolden = (rnd: () => number = Math.random): boolean => rnd() < GOLDEN_ODDS;
/** The toast cheers on every 3rd to 5th sort (spec 3.7): how many sorts until the next one. */
export const cheerGap = (rnd: () => number = Math.random): number => 3 + Math.min(2, Math.floor(rnd() * 3));

export type CheerState = { since: number; gap: number };
export const freshCheers = (rnd: () => number = Math.random): CheerState => ({ since: 0, gap: cheerGap(rnd) });
export type CheerDraw = { line: string | null; golden: boolean; next: CheerState };

/** One sort's cheer: golden at about 1 in 40 where allowed (a golden line at once), else a sort line on every 3rd to
 *  5th sort, or a big one when the sort also set 3 or more matching rows. */
export function sortCheer(s: CheerState, applied: number, canBeGolden: boolean, rnd: () => number = Math.random): CheerDraw {
  if (canBeGolden && rollGolden(rnd)) return { line: nextLine('goldenSort', {}, rnd), golden: true, next: freshCheers(rnd) };
  const since = s.since + 1;
  if (since < s.gap) return { line: null, golden: false, next: { since, gap: s.gap } };
  return { line: nextLine(applied >= 3 ? 'big' : 'sort', {}, rnd), golden: false, next: freshCheers(rnd) };
}

// ---- Growth toward an oak (spec 3.4) ----

export type MilestoneKey = 'first_month' | 'covered' | 'checklist' | 'year' | 'five_years';
export const MILESTONE_NAME: Record<MilestoneKey, string> = {
  first_month: 'the first month fully sorted',
  covered: "the first set-aside covered before it's due",
  checklist: 'the Plan checklist done',
  year: 'a year of history',
  five_years: 'five years of history',
};
// Each milestone's state in words, for a screen reader: the tick or empty circle beside it is hidden (THO-11).
export const MILESTONE_REACHED = ', reached';
export const MILESTONE_NOT_YET = ', not yet';
export const GROWTH_NEXT = '{n} of 5: {next} comes next';
export const GROWTH_ALL = '5 of 5. A full-grown oak.';
export const NEW_GROWTH = 'New growth: {milestone}.';
export const NEW_GROWTH_MONTH = 'New growth: {month} is fully sorted.';
export const NEW_GROWTH_PAST_MONTH = 'New growth: a past month fully sorted.';
export const NEW_GROWTH_PLAIN = 'New growth.';
export const TREE_LABEL = "Steward's oak, {n} of 5 grown";
