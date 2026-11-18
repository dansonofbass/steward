import { money } from '../../lib/format';
import type { ItemKind, ItemRow } from './api';
import { A_MONTH, TODAY } from './copy';
import { dayOf, today as householdToday } from '../../lib/today';

export const KIND_ORDER: ItemKind[] = ['account', 'income', 'insurance', 'document', 'contact'];
const PER_SUFFIX: Record<string, string> = { mo: ' /mo', '3 mo': ' /3 mo', '6 mo': ' /6 mo', yr: ' /yr' };

/** The parent's first name: the first word of the book's first owner label, else "this person" (ledger ruling 1). */
export function parentName(book: { owners: { label: string }[] } | null | undefined): string {
  for (const o of book?.owners ?? []) {
    const first = o.label.trim().split(/\s+/)[0];
    if (first) return first;
  }
  return 'this person';
}

export const possessive = (name: string) => `${name}'s`;

export const fill = (template: string, vars: Record<string, string | number>) =>
  template.replace(/\{(\w+)\}/g, (_, k: string) => String(vars[k] ?? ''));

export function ordinal(n: number): string {
  const s = n % 100 >= 11 && n % 100 <= 13 ? 'th' : ({ 1: 'st', 2: 'nd', 3: 'rd' } as Record<number, string>)[n % 10] ?? 'th';
  return `${n}${s}`;
}

export function amountText(row: ItemRow): string | null {
  if (row.no_balance || row.amount_cents === null) return null;
  return money(row.amount_cents) + (row.amount_per ? PER_SUFFIX[row.amount_per] : '');
}

const local = (iso: string) => { const [y, m, d] = iso.split('-').map(Number); return new Date(y, m - 1, d); };

export function updatedLabel(iso: string, today: Date): string {
  const home = dayOf(today);   // the household's day (issue #26)
  if (iso === home) return TODAY;
  const d = local(iso);
  return d.toLocaleDateString('en-US', iso.slice(0, 4) === home.slice(0, 4) ? { month: 'short', day: 'numeric' } : { month: 'short', year: 'numeric' });
}

export const longDate = (iso: string) => local(iso).toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' });
export const shortDate = (iso: string) => local(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
export const todayIso = (): string => householdToday();

/** "Fidelity Traditional IRA ••3390", leaving the institution out when the name says it (as present.long_label); a contact is "Linda Park, Park & Reyes Law". */
export function longLabel(name: string, institution: string | null, last4: string | null, kind?: string): string {
  if (kind === 'contact') return institution ? `${name}, ${institution}` : name;
  const parts = !institution || name.toLowerCase().includes(institution.toLowerCase()) ? [name] : [institution, name];
  return [...parts, ...(last4 ? [`••${last4}`] : [])].join(' ');
}

export function matches(row: ItemRow, q: string): boolean {
  const s = q.trim().toLowerCase();
  if (!s) return true;
  return [row.name, row.institution ?? '', row.last4 ?? '', row.sub].some((v) => v.toLowerCase().includes(s));
}

export function groupTotal(kind: ItemKind, rows: ItemRow[]): string | null {
  if (kind === 'account') {
    return money(rows.filter((r) => r.status !== 'closed').reduce((sum, r) => sum + (r.amount_cents ?? 0), 0));
  }
  if (kind === 'income' || kind === 'insurance') {
    const counted = rows.filter((r) => r.status !== 'closed' && r.counts_in_totals);
    return `${money(counted.reduce((sum, r) => sum + (r.monthly_cents ?? 0), 0))} ${A_MONTH}`;
  }
  return null;
}
