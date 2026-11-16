/** Phase 17 spec 3.5, enforced in one place: what a moment may show. Every moment calls this before it shows a face,
 *  plays motion or sound, or says a line. Motion and sound are allowed here and still wait for the person's switches
 *  and the device's reduced motion (lib/celebrations.ts). The red-month, fee and parent-book rules come from data the
 *  screens already have: Home's verdict (redMonth), the sorted row's category and the book's kind. */
export type MomentKind =
  // Row 1, the wins.
  | 'sort' | 'caughtUp' | 'import' | 'profileDone' | 'planDone' | 'setAside' | 'payday' | 'tree' | 'gatewayBack'
  // Home's greeting: words only, gone in a red month.
  | 'greeting'
  // Row 2, Steward's own hiccups: a file it couldn't read, a sync that failed, the gateway away.
  | 'oops'
  // Rows 3 to 5: money news; Care, Look into, the change record, Watching; sign-in, reset, invites, backups.
  | 'money' | 'care' | 'flags' | 'changes' | 'watching' | 'signIn' | 'reset' | 'invite' | 'backup'
  // Guided setup (spec 9): a first-run step done and the acorn planted are wins (planted without sound); settings
  // and pairing are nothing.
  | 'setupStep' | 'planted' | 'settings' | 'pairing';
/** `red`: the month is in the red (api/home.ts redMonth). `fee`: the moment is about a fee, a bank, late or interest
 *  charge (isFee). */
export type MomentContext = { parent: boolean; red?: boolean; fee?: boolean };
export type Allowed = { face: boolean; motion: boolean; line: boolean; sound: boolean; golden: boolean };

const NONE: Allowed = { face: false, motion: false, line: false, sound: false, golden: false };
const WINS: ReadonlySet<MomentKind> = new Set(['sort', 'caughtUp', 'import', 'profileDone', 'planDone', 'setAside', 'payday', 'tree', 'gatewayBack', 'setupStep', 'planted']);
const GOLDEN: ReadonlySet<MomentKind> = new Set(['sort', 'caughtUp']);               // never anything about money amounts
const NOT_IN_THE_RED: ReadonlySet<MomentKind> = new Set(['greeting', 'payday', 'sort']);
const WARM_IN_PARENT: ReadonlySet<MomentKind> = new Set(['caughtUp', 'import', 'gatewayBack', 'greeting']);

/** A fee is the Fees category; interest a card charges is filed there too (phase 12 decision 10), and Interest is money
 *  in. */
export const isFee = (category: string | null | undefined): boolean => category === 'fees';

export function momentAllowed(kind: MomentKind, ctx: MomentContext): Allowed {
  if (ctx.fee || (ctx.red && NOT_IN_THE_RED.has(kind))) return NONE;      // claim T6: no cheers on bad news
  if (kind === 'greeting') return { ...NONE, line: true };
  if (kind === 'oops') return ctx.parent ? NONE : { ...NONE, face: true, motion: true };
  if (!WINS.has(kind)) return NONE;
  if (ctx.parent) return kind === 'tree' ? NONE : { ...NONE, line: WARM_IN_PARENT.has(kind) };
  return { face: true, motion: true, line: true, sound: kind !== 'planted', golden: GOLDEN.has(kind) };   // the planting is silent (spec 9)
}
