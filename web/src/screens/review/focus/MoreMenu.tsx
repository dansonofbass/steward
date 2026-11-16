import { Ellipsis } from 'lucide-react';
import { useEffect, useId, useRef, useState, type KeyboardEvent } from 'react';
import { MORE_ACTIONS } from './copy';

export type MenuItem = { key: string; label: string; checked?: boolean; onSelect: () => void };

/** The ⋯ menu (review focus, Focus: one card and Accessibility): an ARIA menu of Ignore, Business, Reimbursable and Add
 *  note. Enter, Space or ↓ opens it on the first item; ↑↓ move; Esc or a choice closes it and gives focus back to ⋯; a
 *  press outside or Tab closes it. Business and Reimbursable are menuitemcheckboxes. */
export function MoreMenu({ items, onOpen }: { items: MenuItem[]; onOpen: (open: boolean) => void }) {
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const list = useRef<HTMLDivElement>(null);
  const id = useId();
  const shown = useRef(onOpen);
  shown.current = onOpen;
  const set = (v: boolean) => { setOpen(v); shown.current(v); };
  const close = () => { set(false); trigger.current?.focus(); };

  useEffect(() => {
    if (!open) return;
    list.current?.querySelector<HTMLElement>('[role^="menuitem"]')?.focus();
    const away = (e: PointerEvent) => {
      const t = e.target as Node;
      if (!list.current?.contains(t) && !trigger.current?.contains(t)) { setOpen(false); shown.current(false); }
    };
    document.addEventListener('pointerdown', away);
    return () => { document.removeEventListener('pointerdown', away); };
  }, [open]);

  const keys = (e: KeyboardEvent<HTMLDivElement>) => {
    const els = [...(list.current?.querySelectorAll<HTMLElement>('[role^="menuitem"]') ?? [])];
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
        aria-expanded={open} aria-controls={open ? id : undefined} onClick={() => { set(!open); }}
        onKeyDown={(e) => { if (e.key === 'ArrowDown') { e.preventDefault(); set(true); } }}>
        <Ellipsis size={20} aria-hidden="true" />
      </button>
      {open && (
        <div ref={list} id={id} role="menu" aria-label={MORE_ACTIONS} className="fmenu__list" onKeyDown={keys}>
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
