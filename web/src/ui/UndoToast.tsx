import { useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { UNDO } from '../lib/copy';
import { useHoldableTimer } from '../lib/useHoldableTimer';
import { useLive } from './Live';
import { Sep } from './Sep';
import './UndoToast.css';

export const TOAST_MS = 10_000;

type Props = {
  text: ReactNode;
  onClose: () => void;
  /** Absent: a toast that only says something (an Undo the server refused). */
  onUndo?: () => void;
  ms?: number;
  /** Review focus P16: a leading stamp tag (SORTED) and a trailing link (Settle). */
  tag?: string | null;
  link?: ReactNode;
  /** Review focus on a phone: above the sticky action bar. */
  lifted?: boolean;
  /** Phase 17 spec 3.7: a cheer on its own full-width row under the receipt and Undo. Skipped whole when that row would wrap. */
  cheer?: ReactNode;
};

/** Nothing vanishes unseen (spec decision 7): a line that names what just left, with Undo, for 10 seconds, paused while
 *  the mouse is on it or focus is in it (review focus P16, WCAG 2.2.1). The Undo itself stays in the journal for 15
 *  minutes. A new toast is a new mount (give it a key), so its 10 seconds start again. */
export function UndoToast({ text, onUndo, onClose, ms = TOAST_MS, tag = null, link = null, lifted = false, cheer = null }: Props) {
  const [hover, setHover] = useState(false);
  const [focus, setFocus] = useState(false);
  useHoldableTimer(0, ms, hover || focus, onClose);
  const cheerEl = useRef<HTMLSpanElement>(null);
  const [fits, setFits] = useState(true);
  // The cheer has its own full-width row under the receipt and Undo, so they never move. Measured before paint: a cheer
  // that would not fit on that one row goes, never cut.
  useLayoutEffect(() => {
    const el = cheerEl.current;
    if (el && el.scrollWidth > el.clientWidth + 1) setFits(false);
  }, [cheer]);
  // WEB-7: a status added with its text already in it is often not read. Inside the app the toast goes into the nearest
  // live region that was already there (the page's, or an open sheet's), so a screen reader hears it arrive as an
  // addition. The region carries the announcement, so the toast isn't a live region of its own there. Without one (a
  // component test) it renders in place, as its own status.
  const live = useLive()?.toasts ?? null;
  const toast = (
    <div className={`undo-toast${lifted ? ' undo-toast--lifted' : ''}`} role={live ? undefined : 'status'} data-testid="undo-toast"
      onPointerEnter={(e) => { if (e.pointerType === 'mouse') setHover(true); }}
      onPointerLeave={(e) => { if (e.pointerType === 'mouse') setHover(false); }}
      onFocus={() => { setFocus(true); }}
      onBlur={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setFocus(false); }}>
      {tag && <><span className="stamp">{tag}</span><Sep /></>}
      <span className="undo-toast__text">{text}</span>
      {link && <>{' '}{link}</>}
      {/* The dot goes with Undo: when Undo wraps under a long receipt, the dot is not left at the end of the line above (#22). */}
      {onUndo && <span className="undo-toast__undo"><Sep /><button type="button" className="link" onClick={onUndo}>{UNDO}</button></span>}
      {cheer && fits && <span className="undo-toast__cheer" data-testid="toast-cheer" ref={cheerEl}>{cheer}</span>}
    </div>
  );
  return live ? createPortal(toast, live) : toast;
}
