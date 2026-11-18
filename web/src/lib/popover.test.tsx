// Issue #27: where the browser has popovers and invokers, the desktop menus are wired to them, and their open state
// follows the browser's toggle events. jsdom has neither, so this installs a small stand-in for both: showPopover and
// hidePopover with their beforetoggle and toggle events, :popover-open, and a commandfor trigger's click. The real
// behaviour (a tap outside, Escape, resizing) is in e2e/menus.spec.ts.
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { BookSummary } from '../api/types';
import { YouMenu } from '../frame/YouMenu';
import { MoreMenu } from '../screens/review/focus/MoreMenu';
import { stubFetch, wrapBook } from '../test-utils';
import { CategoryMenu } from '../ui/CategoryMenu';
import { invokerAttrs, invokerProps } from './popover';

const open = new WeakSet<Element>();
const restore: (() => void)[] = [];
function define(target: object, key: string, desc: PropertyDescriptor) {
  const had = Object.getOwnPropertyDescriptor(target, key);
  Object.defineProperty(target, key, { configurable: true, ...desc });
  restore.push(() => { if (had) Object.defineProperty(target, key, had); else delete (target as Record<string, unknown>)[key]; });
}
function toggle(el: HTMLElement, to: 'open' | 'closed') {
  if ((to === 'open') === open.has(el)) return;
  el.dispatchEvent(Object.assign(new Event('beforetoggle'), { newState: to }));
  if (to === 'open') open.add(el); else open.delete(el);
  el.toggleAttribute('data-open', to === 'open');   // jsdom's own sheet hides [popover]:not(:popover-open), which it never matches
  el.dispatchEvent(Object.assign(new Event('toggle'), { newState: to }));
}
const onClick = (e: MouseEvent) => {
  const b = (e.target as Element).closest?.('button[commandfor]');
  const target = b && document.getElementById(b.getAttribute('commandfor')!);
  if (!target) return;
  const cmd = b.getAttribute('command');
  toggle(target, cmd === 'show-popover' ? 'open' : open.has(target) ? 'closed' : 'open');
};

beforeEach(() => {
  define(HTMLElement.prototype, 'showPopover', { value(this: HTMLElement) { toggle(this, 'open'); } });
  define(HTMLElement.prototype, 'hidePopover', { value(this: HTMLElement) { toggle(this, 'closed'); } });
  define(HTMLButtonElement.prototype, 'commandForElement', { get() { return null; } });
  const matches = Element.prototype.matches;
  define(Element.prototype, 'matches', { value(this: Element, s: string) { return s === ':popover-open' ? open.has(this) : matches.call(this, s); } });
  vi.stubGlobal('CSS', { supports: (q: string) => q === 'anchor-name: --a' });
  document.addEventListener('click', onClick);
  const shown = document.createElement('style');
  shown.textContent = '[popover][data-open] { display: block !important; }';
  document.head.append(shown);
  restore.push(() => shown.remove());
});
afterEach(() => {
  document.removeEventListener('click', onClick);
  while (restore.length) restore.pop()!();
});

const OURS: BookSummary = { slug: 'ours', name: 'Ours', kind: 'household', role: 'manager', available: true, reason: null, owners: [], profile: null };
const ME = { user: { id: 1, username: 'jr', display_name: 'JR Hale', email: 'jr@example.com' }, session: { id: 7, device_label: 'Laptop', created_at: '2026-10-01T00:00:00Z' }, books: [OURS] };

describe('the menus as popovers (issue #27)', () => {
  it('a trigger is its popover\'s invoker: commandfor, or popovertarget where invokers are missing', () => {
    expect(invokerAttrs('m')).toEqual({ commandfor: 'm', command: 'toggle-popover' });
    expect(invokerProps('m', 'show')).toEqual({ commandfor: 'm', command: 'show-popover' });
    delete (HTMLButtonElement.prototype as unknown as Record<string, unknown>).commandForElement;
    expect(invokerAttrs('m')).toEqual({ popovertarget: 'm', popovertargetaction: 'toggle' });
    expect(invokerProps('m')).toEqual({ popoverTarget: 'm', popoverTargetAction: 'toggle' });
  });

  it('the You menu on the rail opens from the initials and follows the browser closing it', async () => {
    stubFetch({ '/api/auth/me': ME });
    wrapBook(<YouMenu variant="rail" />, OURS, '/b/ours');
    const button = await screen.findByRole('button', { name: 'You: JR Hale' });
    const menu = document.getElementById(button.getAttribute('commandfor')!)!;
    expect(menu).toHaveAttribute('popover', 'auto');
    expect(button).toHaveAttribute('command', 'toggle-popover');
    fireEvent.click(button);
    expect(button).toHaveAttribute('aria-expanded', 'true');
    expect(within(menu).getByRole('link', { name: 'Appearance' })).toBeInTheDocument();
    act(() => { menu.hidePopover(); });      // a tap outside, or Escape
    expect(button).toHaveAttribute('aria-expanded', 'false');
  });

  it('the ⋯ menu opens on its first item and closes on a choice, giving focus back', () => {
    const picked = vi.fn();
    const shown = vi.fn();
    render(<MoreMenu items={[{ key: 'a', label: 'Ignore', onSelect: picked }, { key: 'b', label: 'Business', checked: false, onSelect: () => {} }]} onOpen={shown} />);
    const trigger = screen.getByRole('button', { name: 'More actions' });
    const list = document.getElementById(trigger.getAttribute('commandfor')!)!;
    expect(list).toHaveAttribute('popover', 'auto');
    fireEvent.click(trigger);
    expect(shown).toHaveBeenLastCalledWith(true);
    expect(within(list).getByRole('menuitem', { name: 'Ignore' })).toHaveFocus();
    fireEvent.click(within(list).getByRole('menuitem', { name: 'Ignore' }));
    expect(picked).toHaveBeenCalledOnce();
    expect(shown).toHaveBeenLastCalledWith(false);
    expect(trigger).toHaveFocus();
  });

  it('the category menu shows from its trigger, which is its invoker while it is open, and closes with the browser', () => {
    const trigger = document.createElement('button');
    document.body.append(trigger);
    const closed = vi.fn();
    vi.stubGlobal('matchMedia', (q: string) => ({ matches: true, media: q, addEventListener() {}, removeEventListener() {} }));
    const { unmount } = wrapBook(<CategoryMenu anchor={trigger} value={null} onPick={() => {}} onClose={closed} />);
    const menu = document.querySelector<HTMLElement>('.catmenu-pop')!;
    expect(menu).toHaveAttribute('popover', 'auto');
    expect(open.has(menu)).toBe(true);
    expect(within(menu).getByRole('combobox')).toHaveFocus();      // typing at once, as before
    expect(trigger.getAttribute('commandfor')).toBe(menu.id);
    expect(trigger).toHaveAttribute('command', 'show-popover');
    expect(trigger.style.getPropertyValue('anchor-name')).toMatch(/^--a/);
    act(() => { menu.hidePopover(); });
    expect(closed).toHaveBeenCalledOnce();
    unmount();
    expect(trigger).not.toHaveAttribute('commandfor');
    expect(trigger.style.getPropertyValue('anchor-name')).toBe('');
    trigger.remove();
  });
});
