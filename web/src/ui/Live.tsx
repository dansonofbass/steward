import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from 'react';
import './Live.css';

type Live = {
  /** A polite live region that was in the page before any toast: UndoToast renders into it, so the toast is an addition
   *  to a live region a screen reader already knows, which it reads. */
  toasts: HTMLElement | null;
  /** Says a line through a polite live region that was in the page before the line (a route's name, a field's error). */
  say: (text: string) => void;
};

const LiveCtx = createContext<Live | null>(null);

/** The nearest live regions: the page's (RouteFrame), or an open sheet's own, since a modal sheet makes the page behind
 *  it inert and a region there would go unheard. Null outside both (a component test). */
export const useLive = () => useContext(LiveCtx);

/** WEB-7: a live region added with its text already in it is often not read. These two are in the page from the start
 *  and only their contents change. */
export function LiveRegions({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<HTMLElement | null>(null);
  const region = useRef<HTMLDivElement>(null);
  const last = useRef({ text: '', alt: false });
  const say = useCallback((text: string) => {
    const el = region.current;
    if (!el || !text) return;
    // VoiceOver skips a line the same as the one before; a trailing no-break space makes it differ and isn't read.
    const alt = text === last.current.text ? !last.current.alt : false;
    last.current = { text, alt };
    el.textContent = alt ? `${text} ` : text;
  }, []);
  const value = useMemo(() => ({ toasts, say }), [toasts, say]);
  return (
    <LiveCtx.Provider value={value}>
      {children}
      <div ref={setToasts} aria-live="polite" className="live-toasts" data-testid="live-toasts" />
      <div ref={region} aria-live="polite" className="live-said" data-testid="live-said" />
    </LiveCtx.Provider>
  );
}
