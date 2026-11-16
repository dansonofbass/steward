import { CircleHelp } from 'lucide-react';
import { useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { WHAT_THIS_MEANS } from '../lib/copy';
import './Tip.css';

export const TIP_GUTTER = 16;

/** Viewport x for a tooltip `width` wide, centred under `center` where it fits, never nearer than `gutter` to an edge. */
export function tipLeft(center: number, width: number, viewport: number, gutter = TIP_GUTTER): number {
  const w = Math.min(width, viewport - gutter * 2);
  return Math.round(Math.min(Math.max(center - w / 2, gutter), viewport - gutter - w));
}

const canHover = () => typeof window.matchMedia === 'function' && window.matchMedia('(hover: hover)').matches;

/** A (?) button. Its text wraps, always opens downward and stays inside the viewport (16 px gutter). */
export function Tip({ label = WHAT_THIS_MEANS, children }: { label?: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const byHover = useRef(false);
  const wrap = useRef<HTMLSpanElement>(null);
  const btn = useRef<HTMLButtonElement>(null);
  const body = useRef<HTMLSpanElement>(null);
  const id = useId();

  useLayoutEffect(() => {
    const w = wrap.current;
    const b = btn.current;
    const t = body.current;
    if (!open || !w || !b || !t) return;
    const vw = document.documentElement.clientWidth || window.innerWidth;
    const r = b.getBoundingClientRect();
    const x = tipLeft(r.left + r.width / 2, t.offsetWidth, vw);
    t.style.left = `${x - w.getBoundingClientRect().left}px`;
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false); };
    const onPointer = (e: PointerEvent) => { if (!wrap.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener('keydown', onKey);
    document.addEventListener('pointerdown', onPointer);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('pointerdown', onPointer);
    };
  }, [open]);

  return (
    <span
      ref={wrap}
      className={`tip${open ? ' is-open' : ''}`}
      onMouseEnter={() => { if (canHover() && !open) { byHover.current = true; setOpen(true); } }}
      onMouseLeave={() => { if (byHover.current) { byHover.current = false; setOpen(false); } }}
    >
      <button
        ref={btn}
        type="button"
        className="tip__btn"
        aria-label={label}
        aria-expanded={open}
        aria-describedby={open ? id : undefined}
        onClick={() => {
          if (byHover.current) { byHover.current = false; return; } // a click on a hover-opened tip keeps it open
          setOpen((o) => !o);
        }}
      >
        <CircleHelp size={20} aria-hidden="true" />
      </button>
      <span ref={body} id={id} role="tooltip" className="tip__body" hidden={!open}>{children}</span>
    </span>
  );
}
