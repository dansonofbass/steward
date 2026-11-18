import { useEffect, useRef } from 'react';
import { Link } from '../book/links';
import './SubNav.css';

export type SubNavItem = { key: string; to: string; label: string };

/** A section's own pages as tabs under the main navigation: Spending's views, the Plan and Taxes. Navigation, so it reads
 *  as tabs with an underline rather than as buttons. One row: on a phone a row too long for the screen scrolls sideways
 *  (#22), faded at each edge that has more beyond it, and the current tab is scrolled into view. */
export function SubNav({ label, items, on }: { label: string; items: readonly SubNavItem[]; on: string }) {
  const nav = useRef<HTMLElement>(null);
  // Which edges have more tabs beyond them: a first or last tab not wholly in view. An observer, not a scroll-driven
  // animation, so the fades show in every browser.
  useEffect(() => {
    const row = nav.current;
    const first = row?.firstElementChild;
    const last = row?.lastElementChild;
    if (!row || !first || !last || typeof IntersectionObserver === 'undefined') return;
    const seen = new IntersectionObserver((entries) => {
      for (const { target, intersectionRatio } of entries) {
        row.classList.toggle(target === first ? 'more-start' : 'more-end', intersectionRatio < 1);
      }
    }, { root: row, threshold: 1, rootMargin: '1px' });   // the margin: a sub-pixel width never reads as cut
    seen.observe(first);
    if (last !== first) seen.observe(last);
    return () => { seen.disconnect(); };
  }, [items]);
  // The current tab in view, scrolling only the row, never the page: past its fade, so it is never cut.
  useEffect(() => {
    const row = nav.current;
    const tab = row?.querySelector<HTMLElement>('[aria-current="page"]');
    if (!row || !tab) return;
    const fade = parseFloat(getComputedStyle(row).scrollPaddingInlineStart) || 0;
    const box = row.getBoundingClientRect();
    const at = tab.getBoundingClientRect();
    if (at.right > box.right - fade) row.scrollLeft += at.right - (box.right - fade);
    else if (at.left < box.left + fade) row.scrollLeft -= (box.left + fade) - at.left;
  }, [on, items]);
  return (
    <nav ref={nav} className="subnav" aria-label={label}>
      {items.map((i) => (
        <Link key={i.key} to={i.to} className={i.key === on ? 'is-on' : undefined} aria-current={i.key === on ? 'page' : undefined}>
          {i.label}
        </Link>
      ))}
    </nav>
  );
}
