import { monthShort } from '../cashflow/months';

/** "{amount} over" with { amount: '$5' } → "$5 over". */
export const fill = (s: string, vars: Record<string, string | number>) => s.replace(/\{(\w+)\}/g, (_, k: string) => String(vars[k]));
/** "2026-10-01" → "Oct 1" (monthShort reads the month from the date's YYYY-MM). */
export const dayLabel = (iso: string) => `${monthShort(iso)} ${Number(iso.slice(8, 10))}`;
export const joinNames = (names: string[]) => (names.length <= 1 ? names.join('') : `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`);
