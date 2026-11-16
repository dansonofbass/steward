import {
  Banknote, CalendarCheck, CalendarX, Check, Circle, CircleAlert, CircleCheck, Coins, Copy, Flag, Hourglass, Landmark,
  Mail, MailWarning, OctagonAlert, Repeat, TrendingDown, TriangleAlert, UserPlus, type LucideIcon,
} from 'lucide-react';
import type { CheckKey, FlagStatus } from './api';
import { URGENT } from './copy';

export const CHECK_ICONS: Record<CheckKey, LucideIcon> = {
  scam: OctagonAlert, premium: CalendarX, deposit: CalendarX, payee: UserPlus, large: Banknote, unusual: CircleAlert,
  cash: Coins, monthly: Repeat, duplicate: Copy, account: Landmark, low: TrendingDown,
};
export const STATUS_ICONS: Record<FlagStatus, LucideIcon> = { open: Circle, checking: Hourglass, expected: CircleCheck, handled: Check, arrived: CalendarCheck };
/** History lines (watch/views.py): the server sends the icon's name. */
export const WATCH_ICONS: Record<string, LucideIcon> = {
  flag: Flag, mail: Mail, 'mail-warning': MailWarning, banknote: Banknote, 'calendar-check': CalendarCheck,
  hourglass: Hourglass, 'circle-check': CircleCheck, check: Check,
};

/** Every mark is an icon plus a word (README "The frame"). */
export function CheckMark({ check, label }: { check: CheckKey; label: string }) {
  const Icon = CHECK_ICONS[check];
  return <span className="ck"><Icon size={20} aria-hidden="true" />{label}</span>;
}

export function FlagStatusMark({ status, label, by }: { status: FlagStatus; label: string; by?: string | null }) {
  const Icon = STATUS_ICONS[status];
  return <span className={`fs fs--${status}`}><Icon size={20} aria-hidden="true" />{label}{by && <span className="muted fs__by">· {by}</span>}</span>;
}

/** Urgent is the only use of the danger colour on these screens. */
export function UrgentMark() {
  return <span className="urg"><TriangleAlert size={20} aria-hidden="true" />{URGENT}</span>;
}
export const UrgentMarkIcon = () => <TriangleAlert size={20} aria-hidden="true" />;
