import { ChartPie, ClipboardList, HeartHandshake, House, ListChecks, MessageCircleQuestionMark, Sprout, Wallet, type LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';
import { Link, useLocation } from 'react-router-dom';
import type { FlagCount, Kind } from '../api/types';
import { bookHref } from '../book/BookContext';
import { ACCOUNTS, ASK, CARE, HOME, HOME_TO_LOOK_INTO, INVENTORY, PLAN, REVIEW, SPENDING } from '../lib/copy';
import { preloadFocus } from '../screens/review/focus/load';
import { Mark } from './Mark';
import './Nav.css';

export type NavItem = { to: string; label: string; icon: LucideIcon; exact?: boolean; also?: string[]; badge?: boolean; flags?: boolean; preload?: () => void };

/** One book's tabs (phase 10 decision 1; the polish pass made Spending a tab and moved Taxes under Plan, keeping six). All
 * transactions (/transactions) belongs to Accounts in a household and to Inventory in a parent book; Look into and Business
 * open from Home. Settings is under the initials. */
export function navItems(slug: string, kind: Kind): NavItem[] {
  const b = (p: string) => bookHref(slug, p);
  const home: NavItem = { to: b('/'), label: HOME, icon: House, exact: true, also: [b('/look-into'), b('/business')], flags: kind === 'parent' };
  const ask: NavItem = { to: b('/ask'), label: ASK, icon: MessageCircleQuestionMark };
  const review: NavItem = { to: b('/review'), label: REVIEW, icon: ListChecks, badge: true, preload: preloadFocus };
  if (kind === 'parent') {
    return [home, { to: b('/inventory'), label: INVENTORY, icon: ClipboardList, also: [b('/transactions')] },
      { to: b('/care'), label: CARE, icon: HeartHandshake }, ask, review];
  }
  return [home, { to: b('/spending'), label: SPENDING, icon: ChartPie }, { to: b('/accounts'), label: ACCOUNTS, icon: Wallet, also: [b('/transactions')] },
    ask, { to: b('/plan'), label: PLAN, icon: Sprout, also: [b('/taxes')] }, review];
}

/** The household's tabs, for the /design frames. */
export const NAV_ITEMS: NavItem[] = navItems('ours', 'household');

export function isCurrent(item: NavItem, pathname: string): boolean {
  const under = (p: string) => pathname === p || pathname.startsWith(`${p}/`);
  if (item.also?.some(under)) return true;
  return item.exact ? pathname === item.to : under(item.to);
}

type Props = { items: NavItem[]; count?: number; flags?: FlagCount; layout?: 'auto' | 'bar' | 'rail'; home?: string; header?: ReactNode; foot?: ReactNode };

/** Bottom tab bar under 900 px, left rail from 900 px. At the very top of the rail, the mark and "Steward" link to
 *  `home` (the current book's Home); under it `header` (the book switcher); `foot` (the person's initials) at the
 *  bottom. The phone bar has no room for any of them. */
export function Nav({ items, count = 0, flags, layout = 'auto', home, header, foot }: Props) {
  const { pathname } = useLocation();
  return (
    <nav aria-label="Main" className={`nav nav--${layout}`}>
      {home && layout !== 'bar' && (
        <Link to={home} className="nav__brand">
          <Mark size={28} />
          <span className="nav__brand-name">Steward</span>
        </Link>
      )}
      {header && <div className="nav__header">{header}</div>}
      <ul className="nav__list">
        {items.map((item) => {
          const { to, label, icon: Icon } = item;
          const current = isCurrent(item, pathname);
          const n = item.flags ? flags?.count ?? 0 : item.badge ? count : 0;
          const name = item.flags && n > 0 ? HOME_TO_LOOK_INTO.replace('{n}', String(n)) : undefined;
          return (
            <li key={to} className="nav__item">
              <Link to={to} className={`nav__link${current ? ' active' : ''}`} aria-current={current ? 'page' : undefined} aria-label={name}
                onPointerEnter={item.preload} onFocus={item.preload}>
                <Icon size={24} aria-hidden="true" />
                <span className="nav__label">{label}</span>
                {/* A space between the label and the count, so the visible words ("Home 6") read in the link's name. */}
                {n > 0 && ' '}
                {n > 0 && <span className={`nav__count${item.flags && flags?.urgent ? ' nav__count--urgent' : ''}`}>{n > 99 ? '99+' : n}</span>}
              </Link>
            </li>
          );
        })}
      </ul>
      {foot && <div className="nav__foot">{foot}</div>}
    </nav>
  );
}
