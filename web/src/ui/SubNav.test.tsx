import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { SubNav } from './SubNav';

// #22: a tab row too long for a phone stays one row and scrolls; an edge with more tabs beyond it fades. The observer
// below stands in for the browser's, which jsdom lacks: the test says which tabs are wholly in view.
type Seen = { cb: IntersectionObserverCallback; targets: Element[]; options?: IntersectionObserverInit; gone: boolean };
let observers: Seen[] = [];
class FakeObserver {
  seen: Seen;
  constructor(cb: IntersectionObserverCallback, options?: IntersectionObserverInit) { this.seen = { cb, targets: [], options, gone: false }; observers.push(this.seen); }
  observe(el: Element) { this.seen.targets.push(el); }
  disconnect() { this.seen.gone = true; }
}
afterEach(() => { vi.unstubAllGlobals(); observers = []; });

const TABS = ['Overview', 'Try changes', 'Next dollar', 'How it works', 'Taxes'].map((label, i) => ({ key: String(i), to: `/t/${i}`, label }));

function mount() {
  vi.stubGlobal('IntersectionObserver', FakeObserver);
  const r = render(<MemoryRouter><SubNav label="Plan pages" items={TABS} on="0" /></MemoryRouter>);
  const nav = screen.getByRole('navigation', { name: 'Plan pages' });
  const [o] = observers;
  const show = (ratios: [Element, number][]) => o.cb(ratios.map(([target, intersectionRatio]) => ({ target, intersectionRatio }) as IntersectionObserverEntry), o as unknown as IntersectionObserver);
  return { ...r, nav, o, show };
}

describe('SubNav on a phone (#22)', () => {
  it('watches its first and last tab within its own row', () => {
    const { nav, o } = mount();
    expect(o.options?.root).toBe(nav);
    expect(o.targets.map((t) => t.textContent)).toEqual(['Overview', 'Taxes']);
  });

  it('fades the edge that has more tabs beyond it, and neither when every tab is in view', () => {
    const { nav, show } = mount();
    const links = screen.getAllByRole('link');
    show([[links[0], 1], [links[4], 0.4]]);
    expect(nav).toHaveClass('more-end');
    expect(nav).not.toHaveClass('more-start');
    show([[links[0], 0.2], [links[4], 1]]);
    expect(nav).toHaveClass('more-start');
    expect(nav).not.toHaveClass('more-end');
    show([[links[0], 1]]);
    expect(nav.className).toBe('subnav');
  });

  it('stops watching when it goes', () => {
    const { o, unmount } = mount();
    unmount();
    expect(o.gone).toBe(true);
  });

  it('marks the current tab, one row of links', () => {
    mount();
    expect(screen.getByRole('link', { name: 'Overview' })).toHaveAttribute('aria-current', 'page');
    expect(screen.getAllByRole('link')).toHaveLength(5);
  });
});
