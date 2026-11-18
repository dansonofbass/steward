import { Ellipsis } from 'lucide-react';
import { useEffect, useId, useRef, useState, type KeyboardEvent } from 'react';
import { anchoredStyle, anchorName, anchorStyle, canAnchor, canPopover, hide, invokerProps, placeByTrigger, usePopoverOpen } from '../../../lib/popover';
import { MORE_ACTIONS } from './copy';

export type MenuItem = { key: string; label: string; checked?: boolean; onSelect: () => void };

/** The ⋯ menu (review focus, Focus: one card and Accessibility): an ARIA menu of Ignore, Business, Reimbursable and Add
 *  note. Enter, Space or ↓ opens it on the first item; ↑↓ move; Esc or a choice closes it and gives focus back to ⋯; a
 *  press outside or Tab closes it. Business and Reimbursable are menuitemcheckboxes.
 *
 *  Issue #27: the list is a popover, so the browser closes it on a press or tap outside and on Escape, and anchor
 *  positioning keeps it under ⋯. Without popovers (or in a test) it is mounted while open and closed by its own
 *  listener; without anchor positioning it is placed from ⋯'s box as it opens. */
export function MoreMenu({ items, onOpen }: { items: MenuItem[]; onOpen: (open: boolean) => void }) {
  const popover = canPopover();
  const [mounted, setMounted] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const [list, setList] = useState<HTMLDivElement | null>(null);
  const id = useId();
  const anchor = anchorName(id);
  const shown = useRef(onOpen);
  shown.current = onOpen;
  const native = usePopoverOpen(popover ? list : null, {
    before: () => { if (list && trigger.current && !canAnchor()) placeByTrigger(list, trigger.current, 'below', 'end'); },
    after: (now) => { shown.current(now); },
  });
  const open = popover ? native : mounted;
  const set = (v: boolean) => {
    if (popover) { if (v) list?.showPopover(); else hide(list); return; }
    setMounted(v);
    shown.current(v);
  };
  const close = () => { set(false); trigger.current?.focus(); };

  useEffect(() => {
    if (!open) return;
    list?.querySelector<HTMLElement>('[role^="menuitem"]')?.focus();
    if (popover) return;
    const away = (e: PointerEvent) => {
      const t = e.target as Node;
      if (!list?.contains(t) && !trigger.current?.contains(t)) { setMounted(false); shown.current(false); }
    };
    document.addEventListener('pointerdown', away);
    return () => { document.removeEventListener('pointerdown', away); };
  }, [open, list, popover]);

  const keys = (e: KeyboardEvent<HTMLDivElement>) => {
    const els = [...(list?.querySelectorAll<HTMLElement>('[role^="menuitem"]') ?? [])];
    const at = els.indexOf(document.activeElement as HTMLElement);
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      els[(at + (e.key === 'ArrowDown' ? 1 : els.length - 1)) % els.length]?.focus();
    } else if (e.key === 'Home' || e.key === 'End') {
      e.preventDefault();
      els[e.key === 'Home' ? 0 : els.length - 1]?.focus();
    } else if (e.key === 'Escape') {
      e.preventDefault();
      e.stopPropagation();
      close();
    } else if (e.key === 'Tab') {
      set(false);
    }
  };

  return (
    <div className="fmenu">
      <button ref={trigger} type="button" className="fmenu__trigger" aria-label={MORE_ACTIONS} aria-haspopup="menu"
        aria-expanded={open} aria-controls={open ? id : undefined} style={popover ? anchorStyle(anchor) : undefined}
        {...(popover ? invokerProps(id) : { onClick: () => { set(!open); } })}
        onKeyDown={(e) => { if (e.key === 'ArrowDown') { e.preventDefault(); if (open) list?.querySelector<HTMLElement>('[role^="menuitem"]')?.focus(); else set(true); } }}>
        <Ellipsis size={20} aria-hidden="true" />
      </button>
      {(popover || open) && (
        <div ref={setList} id={id} role="menu" aria-label={MORE_ACTIONS} className="fmenu__list" onKeyDown={keys}
          {...(popover ? { popover: 'auto' as const, style: anchoredStyle(anchor) } : {})}>
          {items.map((it) => (
            <button key={it.key} type="button" tabIndex={-1} className="fmenu__item"
              role={it.checked === undefined ? 'menuitem' : 'menuitemcheckbox'} aria-checked={it.checked}
              onClick={() => { close(); it.onSelect(); }}>
              {it.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
