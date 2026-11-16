// What a question is about (Ask about this, Surfaces and P25), eager and tiny: the request the browser sends, which is
// ids only (P6), what the panel needs for its suggestions, and the ?about= grammar. Nothing here imports from
// screens/chat (src/ask/imports.test.ts).

export type AboutIn =
  | { kind: 'account'; id: number }
  | { kind: 'transaction'; id: number }
  | { kind: 'flag'; id: number }
  | { kind: 'category'; category: string; month: string }
  | { kind: 'plan' }
  | { kind: 'care'; id?: number };

/** Which page asked, for the panel's three suggestions (Surfaces › Suggestions). Never sent. */
export type Surface =
  | { kind: 'account'; group: 'everyday' | 'card' | 'invest' }
  | { kind: 'transaction'; category: string }
  | { kind: 'category'; category: string; month: string; over: boolean }
  | { kind: 'plan'; page: 'overview' | 'how' }
  | { kind: 'flag' }
  | { kind: 'care' }
  | { kind: 'care-scenario' };

type HasId = { id: number };

/** Each surface's request, from ids alone: whatever else the page's object holds stays behind. */
export const aboutFor = {
  account: (a: HasId): AboutIn => ({ kind: 'account', id: a.id }),
  transaction: (t: HasId): AboutIn => ({ kind: 'transaction', id: t.id }),
  flag: (f: HasId): AboutIn => ({ kind: 'flag', id: f.id }),
  category: (category: string, month: string): AboutIn => ({ kind: 'category', category, month }),
  plan: (): AboutIn => ({ kind: 'plan' }),
  care: (): AboutIn => ({ kind: 'care' }),
  scenario: (s: HasId): AboutIn => ({ kind: 'care', id: s.id }),
};

/** A copy with only the request's own keys, whatever a caller passed in: what goes to /about and /ask. */
export function cleanAbout(a: AboutIn): AboutIn {
  switch (a.kind) {
    case 'account': case 'transaction': case 'flag': return { kind: a.kind, id: a.id };
    case 'category': return { kind: 'category', category: a.category, month: a.month };
    case 'plan': return { kind: 'plan' };
    case 'care': return a.id === undefined ? { kind: 'care' } : { kind: 'care', id: a.id };
  }
}

/** "account:12", "category:dining:2026-10", "transaction:345", "plan", "flag:7", "care", "care:3" (P25). */
export function aboutParam(a: AboutIn): string {
  switch (a.kind) {
    case 'category': return `category:${a.category}:${a.month}`;
    case 'plan': return 'plan';
    case 'care': return a.id === undefined ? 'care' : `care:${a.id}`;
    default: return `${a.kind}:${a.id}`;
  }
}

const ID = /^[1-9][0-9]{0,9}$/;
const WITH_ID = ['account', 'transaction', 'flag', 'care'];

/** The address's ?about=, or null for anything that isn't exactly one of P25's forms. */
export function parseAboutParam(s: string | null): AboutIn | null {
  if (!s) return null;
  const p = s.split(':');
  if (p.length === 1 && p[0] === 'plan') return { kind: 'plan' };
  if (p.length === 1 && p[0] === 'care') return { kind: 'care' };
  if (p.length === 2 && WITH_ID.includes(p[0]) && ID.test(p[1])) return { kind: p[0], id: Number(p[1]) } as AboutIn;
  if (p.length === 3 && p[0] === 'category' && /^[a-z_]{1,40}$/.test(p[1]) && /^\d{4}-(0[1-9]|1[0-2])$/.test(p[2])) {
    return { kind: 'category', category: p[1], month: p[2] };
  }
  return null;
}
