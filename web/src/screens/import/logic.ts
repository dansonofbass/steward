import type { Account } from '../../api/types';
import type { Field, Mapping, SentLayout, StagedFile } from './api';
import * as C from './copy';

export const MAX_FILES = 30;
export const MAX_BYTES = 5 * 1024 * 1024;
const CARD = new Set(['credit', 'business_credit']);
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

export type Answers = { mapping: Mapping; negate: boolean | null; dateFormat: string | null };
export type Row = {
  key: string; name: string; status: 'reading' | 'ready' | 'error' | 'expired'; file: StagedFile | null; error: string | null;
  accountId: number | null; answers: Answers | null; confirmed: boolean; removed: boolean; blob?: File;
};

export const count = (n: number) => n.toLocaleString('en-US');
export function monthDay(iso: string): string {
  const [, m, d] = iso.slice(0, 10).split('-').map(Number);
  return `${MONTHS[m - 1]} ${d}`;
}
export const kindOf = (a: Account | null | undefined): 'credit' | 'bank' | null => (a ? (CARD.has(a.type) ? 'credit' : 'bank') : null);

export function initialAnswers(f: StagedFile): Answers | null {
  return f.layout ? { mapping: { ...f.layout.mapping }, negate: null, dateFormat: f.layout.date_format } : null;
}

const fixedBy = (m: Mapping) => m.direction !== undefined || (m.amount === undefined && m.debit !== undefined && m.credit !== undefined);

/** P14: a remembered layout whose file's sign evidence is clear and says the other way. */
export function contradicted(f: StagedFile, a: Account | null | undefined): boolean {
  const k = kindOf(a);
  if (!f.layout || f.state !== 'remembered' || f.layout.sign_fixed || !k) return false;
  const v = f.layout.sign[k].verdict;
  return v !== null && (v === 'negate') !== Boolean(f.layout.negate);
}

/** The row asks something: a new layout's confirm (P12), or a remembered layout's sign again (P14). */
export const asks = (r: Row, a: Account | null | undefined) => !!r.file && (r.file.state === 'new' || contradicted(r.file, a));

export function signShows(r: Row, a: Account | null | undefined): boolean {
  const m = r.answers?.mapping;
  return !!r.file?.layout && !!m && asks(r, a) && !fixedBy(m) && m.amount !== undefined;
}

/** The sign the file will import with: the person's answer, else what the columns or the format say, else a clear
 *  verdict for the picked account's kind (pre-selected, P12), else null: asked, with nothing pre-selected (P10). */
export function negateOf(r: Row, a: Account | null | undefined): boolean | null {
  const f = r.file;
  if (!f?.layout || !r.answers) return null;
  if (r.answers.negate !== null) return r.answers.negate;
  if (fixedBy(r.answers.mapping)) return false;
  if (f.layout.sign_fixed || (f.state === 'remembered' && !contradicted(f, a))) return Boolean(f.layout.negate);
  const k = kindOf(a);
  if (!k || f.state !== 'new') return null;
  const v = f.layout.sign[k].verdict;
  return v === null ? null : v === 'negate';
}

export function questions(r: Row, a: Account | null | undefined): number {
  const f = r.file;
  if (!f?.layout || !r.answers) return 0;
  const sign = signShows(r, a) && negateOf(r, a) === null ? 1 : 0;
  const date = f.state === 'new' && f.layout.date_question && !r.answers.dateFormat ? 1 : 0;
  return sign + date;
}

export function validity(m: Mapping): 'ok' | 'invalid' {
  return m.date !== undefined && m.description !== undefined && (m.amount !== undefined || (m.debit !== undefined && m.credit !== undefined))
    ? 'ok' : 'invalid';
}

/** Choosing a field another column already has moves it: the other column becomes Ignore. */
export function moveField(m: Mapping, column: number, field: Field | 'ignore'): Mapping {
  const out: Mapping = {};
  for (const [k, i] of Object.entries(m) as [Field, number][]) if (i !== column && k !== field) out[k] = i;
  if (field !== 'ignore') out[field] = column;
  return out;
}

export function fieldAt(m: Mapping, column: number): Field | 'ignore' {
  const hit = (Object.entries(m) as [Field, number][]).find(([, i]) => i === column);
  return hit ? hit[0] : 'ignore';
}

/** Plan Engineering choice 3: the account's institution, or the account's name when it's manual. */
export const layoutLabel = (a: Account | null | undefined) => (a ? (a.institution === 'Manual' ? a.name : a.institution).slice(0, 60) : '');

export function signCopy(kind: 'credit' | 'bank' | null, lean: 'positive' | 'negative' | null) {
  const card = kind === 'credit';
  return { legend: lean ? (card ? C.CARD_LEAN : C.BANK_LEAN).replace('{lean}', lean) : C.NO_LEAN,
    options: card ? C.CARD_OPTIONS : C.BANK_OPTIONS };
}

export function tag(r: Row, a: Account | null | undefined): string {
  if (r.status === 'reading') return C.READING;
  if (r.status === 'expired') return '';                 // the name stays, so the person knows which file to add again
  const f = r.file;
  if (r.status === 'error' || !f) return r.error ?? f?.error ?? '';
  let t: string;
  if (f.kind === 'ofx') t = C.TAG_OFX.replace('{n}', count(f.rows));
  else if (f.state === 'new') {
    const q = questions(r, a);
    t = r.confirmed ? (a ? C.TAG_NEW_DONE.replace('{label}', layoutLabel(a)) : C.NEW_LAYOUT)
      : q === 0 ? C.TAG_NEW_CHECK : q === 1 ? C.TAG_NEW_ONE : C.TAG_NEW_N.replace('{n}', String(q));
  } else if (f.state === 'remembered') {
    t = (contradicted(f, a) && r.answers?.negate == null ? C.TAG_ASK_AGAIN : C.TAG_REMEMBERED).replace('{label}', f.label ?? '');
  } else t = C.TAG_KNOWN.replace('{label}', f.label ?? '').replace('{n}', count(f.rows));
  return f.imported_before ? t + C.TAG_BEFORE.replace('{date}', monthDay(f.imported_before)) : t;
}

/** Ready (spec, Flow states): an account, and every question answered; an error or expired row is left out of the
 *  batch and never waited on. */
export function ready(r: Row, a: Account | null | undefined): boolean {
  if (r.removed || r.status === 'error' || r.status === 'expired') return true;
  if (r.status !== 'ready' || !r.file || r.accountId === null) return false;
  const f = r.file;
  if (f.state === 'new') return r.confirmed && questions(r, a) === 0 && !!r.answers && validity(r.answers.mapping) === 'ok';
  if (contradicted(f, a)) return r.answers?.negate != null;
  return true;
}

export function sent(r: Row, a: Account | null | undefined): SentLayout | null {
  const f = r.file;
  if (!f?.layout || !r.answers || !asks(r, a)) return null;
  return { mapping: r.answers.mapping, negate: negateOf(r, a), date_format: r.answers.dateFormat ?? f.layout.date_format };
}
