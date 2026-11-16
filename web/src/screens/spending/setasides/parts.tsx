import { Building2, Car, ChevronRight, CircleAlert, CircleCheck, CircleDashed, Gift, House, Landmark, PiggyBank, ShieldCheck, Store, SunMedium, type LucideIcon } from 'lucide-react';
import type { SetAsideDismissed, SetAsideRow, SetAsideState, SetAsideSuggestion } from '../../../api/types';
import { Link } from '../../../book/links';
import { label } from '../../../lib/categories';
import { dollars } from '../../../lib/format';
import * as C from './copy';
import { costText, dueWhen, fill, stateLine, stateTone } from './model';

const STATE_ICON: Record<SetAsideState, LucideIcon> = { short: CircleAlert, behind: CircleAlert, not_paid: CircleAlert, on_track: CircleCheck, no_account: CircleDashed };
/** A row's icon from its category or name; the piggy bank when nothing fits. */
export function rowIcon(name: string, category: string | null): LucideIcon {
  const n = name.toLowerCase();
  if (category === 'taxes' || n.includes('tax')) return Landmark;
  if (category === 'insurance' || n.includes('insurance')) return ShieldCheck;
  if (category === 'transport' || n.includes('car')) return Car;
  if (n.includes('holiday') || n.includes('gift')) return Gift;
  if (n.includes('camp')) return SunMedium;
  if (category === 'housing' || n.includes('hoa')) return Building2;
  if (category === 'home' || n.includes('roof') || n.includes('heater') || n.includes('heating')) return House;
  if (category === 'shopping') return Store;
  return PiggyBank;
}

export function StateIcon({ state }: { state: SetAsideState }) {
  const Icon = STATE_ICON[state];
  return <Icon className="i" size={16} aria-hidden="true" />;
}

/** One set-aside on the list: name, cost and next due, the monthly amount, and the state in the list's words. */
export function SetAsideRowView({ r, asOf }: { r: SetAsideRow; asOf: string }) {
  const Icon = rowIcon(r.name, r.category);
  return (
    <Link className={`sa-row is-${stateTone(r.state)}`} to={`/spending/setasides/${r.id}`} data-testid="sa-row" data-state={r.state}>
      <Icon className="i" size={24} aria-hidden="true" />
      <span className="sa-row__name">{r.name}</span>
      <span className="sa-row__sub">{`${costText(r)} · ${dueWhen(r, asOf)}`}{r.is_estimate && <span className="tag tag--warn">{C.ESTIMATE}</span>}</span>
      <span className="sa-row__month"><span className="money money--m">{dollars(r.monthly_cents)}</span><span className="small">{C.A_MONTH}</span></span>
      <span className="sa-row__state"><StateIcon state={r.state} />{stateLine(r)}</span>
      <ChevronRight className="i" size={20} aria-hidden="true" />
    </Link>
  );
}

/** "Change first" opens Add with the suggestion's fields in the address (engineering choice 13). */
export function suggestionHref(s: SetAsideSuggestion): string {
  const q = new URLSearchParams({ name: s.name, kind: s.kind, amount: String(s.amount_cents), due_month: String(s.due_month), due_day: String(s.due_day) });
  if (s.second_month !== null && s.second_day !== null) { q.set('second_month', String(s.second_month)); q.set('second_day', String(s.second_day)); }
  q.set('payee_key', s.payee_key);
  q.set('category', s.category);
  return `/spending/setasides/new?${q}`;
}

export function DismissedRow({ d, canEdit, onRestore }: { d: SetAsideDismissed; canEdit: boolean; onRestore: () => void }) {
  return (
    <div className="sa-row sa-row--line is-none" data-testid="sa-dismissed">
      <CircleDashed className="i" size={24} aria-hidden="true" />
      <span className="sa-row__name muted">{d.payee_name}</span>
      <span className="sa-row__sub">{fill(C.NOT_A_SET_ASIDE, { label: label(d.category) })}{canEdit && <> · <button type="button" className="link link--quiet sa-link--s" onClick={onRestore} aria-label={fill(C.BRING_IT_BACK_NAMED, { name: d.payee_name })}>{C.BRING_IT_BACK}</button></>}</span>
      <span className="money money--m muted">{dollars(d.monthly_cents)}</span>
      <span className="i" />
    </div>
  );
}
