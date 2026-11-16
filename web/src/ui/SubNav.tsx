import { Link } from '../book/links';
import './SubNav.css';

export type SubNavItem = { key: string; to: string; label: string };

/** A section's own pages as tabs under the main navigation: Spending's views, the Plan and Taxes. Navigation, so it reads
 *  as tabs with an underline rather than as buttons. */
export function SubNav({ label, items, on }: { label: string; items: readonly SubNavItem[]; on: string }) {
  return (
    <nav className="subnav" aria-label={label}>
      {items.map((i) => (
        <Link key={i.key} to={i.to} className={i.key === on ? 'is-on' : undefined} aria-current={i.key === on ? 'page' : undefined}>
          {i.label}
        </Link>
      ))}
    </nav>
  );
}
