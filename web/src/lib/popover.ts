import { useEffect, useRef, useState, type CSSProperties } from 'react';

// Issue #27: the desktop menus are native popovers. popover="auto" puts a menu in the top layer, and the browser closes
// it on a press or a tap outside and on Escape; the trigger is its invoker (commandfor, or popovertarget where
// invokers are missing), so a press on the trigger never counts as outside. CSS anchor positioning keeps a menu by its
// trigger through resizing, zooming and scrolling. Each piece is detected, and a browser without it gets the old way:
// no popover, the menu's own listeners; no anchor positioning, a place worked out from the trigger's box when it opens.

export const canPopover = (): boolean => typeof HTMLElement !== 'undefined' && 'showPopover' in HTMLElement.prototype;
const canInvoke = (): boolean => typeof HTMLButtonElement !== 'undefined' && 'commandForElement' in HTMLButtonElement.prototype;
export const canAnchor = (): boolean => typeof CSS !== 'undefined' && typeof CSS.supports === 'function' && CSS.supports('anchor-name: --a');

/** The trigger's half of the pair, as DOM attributes: what makes it the popover's invoker. Empty without popovers. */
export function invokerAttrs(popoverId: string, action: 'toggle' | 'show' = 'toggle'): Record<string, string> {
  if (!canPopover()) return {};
  return canInvoke() ? { commandfor: popoverId, command: `${action}-popover` } : { popovertarget: popoverId, popovertargetaction: action };
}

/** The same as React props (React knows popoverTarget by its camel-case name, and passes commandfor through). */
export function invokerProps(popoverId: string, action: 'toggle' | 'show' = 'toggle'): Record<string, string> {
  const a = invokerAttrs(popoverId, action);
  return 'popovertarget' in a ? { popoverTarget: a.popovertarget, popoverTargetAction: a.popovertargetaction } : a;
}

/** A dashed ident for anchor-name from React's useId, which uses characters an ident can't. */
export const anchorName = (id: string): string => `--a${id.replace(/[^\w-]/g, '')}`;
// React sets an unknown style name as a property, which is what these are; csstype doesn't list them yet.
export const anchorStyle = (name: string): CSSProperties => ({ anchorName: name } as CSSProperties);
export const anchoredStyle = (name: string): CSSProperties => ({ positionAnchor: name } as CSSProperties);

/** Whether a popover is open, from its toggle events. `before` runs as it is about to open (beforetoggle, before the
 *  browser draws it), `after` once it has opened or closed. */
export function usePopoverOpen(el: HTMLElement | null, on: { before?: () => void; after?: (open: boolean) => void } = {}): boolean {
  const [open, setOpen] = useState(false);
  const handlers = useRef(on);
  handlers.current = on;
  useEffect(() => {
    if (!el) return;
    const state = (e: Event) => (e as Event & { newState?: string }).newState;
    const onBefore = (e: Event) => { if (state(e) === 'open') handlers.current.before?.(); };
    const onToggle = (e: Event) => {
      const now = state(e) === 'open';
      setOpen(now);
      handlers.current.after?.(now);
    };
    el.addEventListener('beforetoggle', onBefore);
    el.addEventListener('toggle', onToggle);
    return () => { el.removeEventListener('beforetoggle', onBefore); el.removeEventListener('toggle', onToggle); };
  }, [el]);
  return open;
}

/** Closes a popover if it is open. */
export function hide(el: HTMLElement | null): void {
  if (el?.matches(':popover-open')) el.hidePopover();
}

/** Without anchor positioning: the menu's place from the trigger's box, set as it is about to open, so it never shows
 *  anywhere else first. Page coordinates (a top-layer box is placed against the initial containing block, which
 *  scrolls with the page). Above or below the trigger; by its start or end edge, or as wide as it. */
export function placeByTrigger(menu: HTMLElement, trigger: HTMLElement, side: 'above' | 'below', align: 'start' | 'end' | 'stretch', gap = 4): void {
  const r = trigger.getBoundingClientRect();
  const vw = document.documentElement.clientWidth || window.innerWidth;
  const vh = document.documentElement.clientHeight || window.innerHeight;
  const s = menu.style;
  s.position = 'absolute';
  s.inset = 'auto';
  s.margin = '0';
  if (side === 'above') s.bottom = `${Math.round(vh - window.scrollY - r.top + gap)}px`;
  else s.top = `${Math.round(r.bottom + window.scrollY + gap)}px`;
  if (align === 'end') s.right = `${Math.round(vw - window.scrollX - r.right)}px`;
  else s.left = `${Math.round(r.left + window.scrollX)}px`;
  if (align === 'stretch') s.width = `${Math.round(r.width)}px`;
}
