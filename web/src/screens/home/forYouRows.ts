import type { ForYouItem, HomeData } from '../../api/home';
import type { TaxNotice } from '../../api/hooks';
import { inLater, type ProfileState } from '../../api/profile';
import type { ReviewQueue } from '../../api/types';
import { PROFILE_LINE } from '../../lib/copy';
import { dollars } from '../../lib/format';
import { SECTION_NAME, SECTION_STEPS, sectionPath } from '../../lib/profileSections';
import { overLine, type OverLine } from '../../lib/spendingLine';
import * as C from './copy';

/** P18: six rows show; the rest wait behind "{n} more". */
export const SHOWN = 6;
export type Row = { key: string; text: string; amber: boolean; action?: { label: string; to: string }; dismiss?: number; later?: boolean };
export type Inputs = { data: HomeData; canEdit: boolean; review?: ReviewQueue; tax?: TaxNotice; profile?: ProfileState };

const fill = (s: string, vars: Record<string, string | number>) => s.replace(/\{(\w+)\}/g, (_, k: string) => String(vars[k]));
type Of<K extends ForYouItem['kind']> = Extract<ForYouItem, { kind: K }>;
const of = <K extends ForYouItem['kind']>(data: HomeData, kind: K): Of<K>[] => data.for_you.filter((x): x is Of<K> => x.kind === kind);

/** The over line's sentence without its trailing link (engineering choice 20): For you's action column holds See ›. */
export function overText(line: OverLine): string {
  const bits = line.bits[line.bits.length - 1]?.to ? line.bits.slice(0, -2) : line.bits;
  return bits.map((b) => b.text).join('');
}

/** P19: sign-in problems go to Banks, a chat problem to Chat's sent log, mail and anything else to the Log. */
function eventAction(kind: string): { label: string; to: string } {
  if (kind === 'sync') return { label: C.ACT_FIX, to: '/settings/banks' };
  if (kind === 'import') return { label: C.ACT_IMPORT, to: '/settings/import' };
  if (kind === 'chat') return { label: C.ACT_SEE, to: '/settings/chat/sent' };
  return { label: C.ACT_SEE, to: '/settings/log' };
}

/** For you's rows in P18's order: event problems, over target, same account, untyped accounts, Review, owed to you,
 *  tax, Profile. A viewer's event rows carry no action (engineering choice 17) and there is no Review row for them;
 *  the server already leaves out the same-account and untyped rows (P22). Amber: an event at warn or error, and over
 *  target with a category clearly over. */
export function forYouRows({ data, canEdit, review, tax, profile }: Inputs): Row[] {
  const rows: Row[] = [];
  for (const e of of(data, 'event')) {
    rows.push({ key: `event-${e.id}`, text: e.message, amber: e.level === 'error' || e.level === 'warn',
      ...(canEdit ? { action: eventAction(e.event_kind), dismiss: e.id } : {}) });
  }
  const flex = data.signs.flexible;
  const line = flex.rows.length > 0
    ? overLine({ month: data.month, current: true, day: data.day, head: { everyday_target_cents: flex.target_cents ?? 0 }, everyday: flex.rows })
    : null;
  if (line && line.tone !== 'quiet') {
    const to = flex.rows.length === 1 ? `/spending/${flex.rows[0].category}?month=${data.month}` : `/spending?month=${data.month}#flexible`;
    rows.push({ key: 'over', text: overText(line), amber: line.tone === 'amber', action: { label: C.ACT_SEE, to } });
  }
  for (const s of of(data, 'same_account')) {
    rows.push({ key: 'same', text: s.n === 1 && s.name ? fill(C.SAME_ONE, { name: s.name }) : fill(C.SAME_N, { n: s.n }), amber: false,
      action: { label: C.ACT_ANSWER, to: '/accounts' } });
  }
  for (const u of of(data, 'untyped')) {
    rows.push({ key: 'untyped', text: u.n === 1 ? C.UNTYPED_ONE : fill(C.UNTYPED_N, { n: u.n }), amber: false,
      action: { label: C.ACT_SET, to: '/settings/banks' } });
  }
  const sort = (review?.count ?? 0) + (review?.business_count ?? 0);
  if (canEdit && sort > 0) {
    rows.push({ key: 'review', text: sort === 1 ? C.REVIEW_ONE : fill(C.REVIEW_N, { n: sort }), amber: false,
      action: { label: C.ACT_REVIEW, to: '/review' } });
  }
  for (const o of of(data, 'owed')) {
    const see = { label: C.ACT_SEE, to: '/spending/reimbursements' };
    o.payers.forEach((p, i) => rows.push({ key: `owed-${i}`, text: fill(C.OWES_YOU, { payer: p.name, amount: dollars(p.cents) }), amber: false, action: see }));
    if (o.others.n > 0) {
      const text = o.others.n === 1 ? fill(C.OTHER_OWES, { amount: dollars(o.others.cents) }) : fill(C.OTHERS_OWE, { n: o.others.n, amount: dollars(o.others.cents) });
      rows.push({ key: 'owed-others', text, amber: false, action: see });
    }
  }
  if (tax?.notice) rows.push({ key: 'tax', text: tax.notice.line, amber: false, action: { label: C.ACT_SEE, to: '/taxes' } });
  const next = profile && !profile.finished && !inLater(profile.me) ? profile.sections.find((s) => s.key === profile.next) : undefined;
  if (next) {
    rows.push({ key: 'profile', amber: false, later: true,
      text: PROFILE_LINE.replace('{n}', String(profile!.done)).replace('{section}', SECTION_NAME[next.key]).replace('{m}', String(next.minutes)),
      action: { label: C.ACT_CONTINUE, to: sectionPath(next.key, next.resume_step ?? SECTION_STEPS[next.key][0]) } });
  }
  return rows;
}
