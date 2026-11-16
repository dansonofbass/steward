import { ChevronDown, Search } from 'lucide-react';
import { useEffect, useId, useLayoutEffect, useRef, useState, type KeyboardEvent } from 'react';
import { createPortal } from 'react-dom';
import { useUsual } from '../api/hooks';
import { CATEGORY_GROUPS, findCategories, label, UNSORTED } from '../lib/categories';
import { CAT_UNSURE, CATEGORY, FIND_CATEGORY, NO_CATEGORY_MATCH, TYPE_TO_FIND, YOUR_USUAL } from '../lib/copy';
import { composing } from '../lib/ime';
import { menuPlace, type MenuPlace } from '../lib/menuPlace';
import { useWide } from '../lib/useWide';
import { Sheet } from './Sheet';
import './CategoryMenu.css';

/** Sorting redesign, Opening: a fine pointer and at least 900 px get the popover; everything else the half sheet. */
export const DESKTOP = '(pointer: fine) and (min-width: 900px)';

type Section = { id: string; name: string | null; keys: readonly string[] };

/** What the menu lists: with nothing typed, your usual, then the five groups (and Not sure yet where it is allowed);
 *  with something typed, one ranked list (findCategories). */
export function menuSections(q: string, usual: readonly string[], withUnsorted: boolean): Section[] {
  if (q.trim()) return [{ id: 'found', name: null, keys: findCategories(q, usual, withUnsorted) }];
  const out: Section[] = [];
  const mine = usual.filter((k) => k !== UNSORTED);
  if (mine.length) out.push({ id: 'usual', name: YOUR_USUAL, keys: mine });
  CATEGORY_GROUPS.forEach((g, i) => out.push({ id: `g${i}`, name: g.name, keys: g.keys }));
  if (withUnsorted) out.push({ id: 'unsure', name: CAT_UNSURE, keys: [UNSORTED] });
  return out;
}

/** One menu at a time (spec, The picker): a menu that opens closes the one before it. */
let closeOpen: (() => void) | null = null;

type MenuProps = {
  anchor: HTMLElement | null; value: string | null; title?: string; withUnsorted?: boolean;
  onPick: (key: string) => void; onClose: () => void;
};

/** Sorting redesign, The picker: an ARIA combobox (a search box and a listbox, aria-activedescendant). Mount it only
 *  while open. Desktop: a popover under or above the trigger, two columns of plain rows. Phone: a half sheet. */
export function CategoryMenu({ anchor, value, title = CATEGORY, withUnsorted = false, onPick, onClose }: MenuProps) {
  const desktop = useWide(DESKTOP);
  const usual = useUsual().data?.keys ?? [];
  const [q, setQ] = useState('');
  const [active, setActive] = useState(0);
  const [place, setPlace] = useState<MenuPlace | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const pop = useRef<HTMLDivElement>(null);
  const moved = useRef(false);
  const closer = useRef(onClose);
  closer.current = onClose;
  const id = useId();
  const sections = menuSections(q, usual, withUnsorted);
  const flat = sections.flatMap((s) => s.keys.map((k) => ({ key: k, id: `${id}-${s.id}-${k}` })));
  const at = Math.min(active, Math.max(0, flat.length - 1));
  const current = flat.length ? flat[at] : null;
  const activeId = current?.id;

  useEffect(() => {
    const mine = () => closer.current();
    closeOpen?.();
    closeOpen = mine;
    return () => { if (closeOpen === mine) closeOpen = null; };
  }, []);

  useLayoutEffect(() => {
    if (!desktop) return;
    const r = anchor?.getBoundingClientRect() ?? { left: 16, top: 16, bottom: 16 };
    setPlace(menuPlace(r, document.documentElement.clientWidth || window.innerWidth, window.innerHeight, window.scrollX, window.scrollY));
  }, [desktop, anchor]);

  useEffect(() => { if (desktop && place) input.current?.focus(); }, [desktop, place]);

  useEffect(() => {
    if (!desktop) return;
    const onDown = (e: PointerEvent) => {
      const t = e.target as Node;
      if (!pop.current?.contains(t) && !anchor?.contains(t)) closer.current();
    };
    document.addEventListener('pointerdown', onDown);
    return () => document.removeEventListener('pointerdown', onDown);
  }, [desktop, anchor]);

  // Only after the user moves the active row, and only once a desktop popover is placed: scrolling an unplaced
  // (hidden, end-of-body) popover would scroll the page and leave the popover off screen.
  useLayoutEffect(() => {
    if (!moved.current || !(desktop ? place : true)) return;
    if (activeId) document.getElementById(activeId)?.scrollIntoView?.({ block: 'nearest' });
  }, [activeId, desktop, place]);

  const leave = () => { anchor?.focus(); onClose(); };
  const pick = (k: string) => { anchor?.focus(); onPick(k); };
  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    const n = flat.length;
    if (e.key === 'ArrowDown' && n) { e.preventDefault(); moved.current = true; setActive((at + 1) % n); }
    else if (e.key === 'ArrowUp' && n) { e.preventDefault(); moved.current = true; setActive((at - 1 + n) % n); }
    else if (e.key === 'Enter') { e.preventDefault(); if (current && !composing(e)) pick(current.key); }
    else if (e.key === 'Escape' || e.key === 'Tab') { e.preventDefault(); e.stopPropagation(); leave(); }
  };

  const listId = `${id}-list`;
  const option = (s: Section, k: string) => {
    const oid = `${id}-${s.id}-${k}`;
    return (
      <div key={oid} id={oid} role="option" aria-selected={oid === activeId}
        className={`catmenu__opt${oid === activeId ? ' is-active' : ''}${k === value ? ' is-current' : ''}`}
        onMouseDown={(e) => { e.preventDefault(); }} onClick={() => { pick(k); }}>
        {label(k)}
      </div>
    );
  };
  const body = (
    <div className="catmenu">
      <label className="catmenu__search">
        <Search size={20} aria-hidden="true" />
        <input ref={input} type="text" role="combobox" value={q} placeholder={TYPE_TO_FIND} aria-label={FIND_CATEGORY}
          aria-expanded="true" aria-controls={listId} aria-autocomplete="list" aria-activedescendant={activeId}
          autoComplete="off" spellCheck={false} enterKeyHint="done"
          onChange={(e) => { moved.current = true; setQ(e.target.value); setActive(0); }} onKeyDown={onKey} />
      </label>
      {flat.length === 0 ? (
        <p className="catmenu__empty" role="status">{NO_CATEGORY_MATCH.replace('{q}', q.trim())}</p>
      ) : (
        <div id={listId} role="listbox" aria-label={title} className={`catmenu__list${q.trim() ? '' : ' catmenu__list--grouped'}`}>
          {sections.map((s) => (s.name === null ? s.keys.map((k) => option(s, k)) : (
            <div key={s.id} role="group" aria-labelledby={`${id}-${s.id}-h`} className={`catmenu__group${s.id === 'usual' ? ' catmenu__group--usual' : ''}`}>
              <div id={`${id}-${s.id}-h`} className="catmenu__head">{s.name}</div>
              {s.keys.map((k) => option(s, k))}
            </div>
          )))}
        </div>
      )}
    </div>
  );

  if (!desktop) {
    return <Sheet open onClose={onClose} title={title} focusRef={input} className="catmenu-sheet">{body}</Sheet>;
  }
  return createPortal(
    <div ref={pop} className="catmenu-pop" role="dialog" aria-label={title}
      style={place ? { left: place.left, top: place.top, width: place.width, height: place.height } : { visibility: 'hidden' }}>
      {body}
    </div>,
    document.body,
  );
}

type FieldProps = { value: string; onChange: (key: string) => void; title?: string; disabled?: boolean; withUnsorted?: boolean };

/** A form field that looks like the other selects and opens the CategoryMenu (the transaction detail, Category rules). */
export function CategoryField({ value, onChange, title = CATEGORY, disabled = false, withUnsorted = true }: FieldProps) {
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const id = useId();
  return (
    <div className="field">
      <span className="field__label" id={`${id}-l`}>{title}</span>
      <button ref={trigger} type="button" className="catmenu__trigger" aria-haspopup="dialog" aria-expanded={open}
        aria-labelledby={`${id}-l ${id}-v`} disabled={disabled} onClick={() => { setOpen((o) => !o); }}>
        <span id={`${id}-v`}>{label(value)}</span>
        <ChevronDown size={20} aria-hidden="true" />
      </button>
      {open && (
        <CategoryMenu anchor={trigger.current} value={value} title={title} withUnsorted={withUnsorted}
          onPick={(k) => { setOpen(false); onChange(k); }} onClose={() => { setOpen(false); }} />
      )}
    </div>
  );
}
