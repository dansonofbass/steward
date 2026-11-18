import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode, type RefObject } from 'react';
import './Live.css';

type Live = {
  /** A polite live region that was in the page before any toast: UndoToast renders into it, so the toast is an addition
   *  to a live region a screen reader already knows, which it reads. */
  toasts: HTMLElement | null;
  /** Says a line through a polite live region that was in the page before the line (a route's name, a field's error,
   *  a notice that has appeared). */
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
  // Lines said in the same moment (a page change says its name as a notice on the new page appears) are said
  // together: each would otherwise replace the one before it unheard.
  const together = useRef<string[] | null>(null);
  const say = useCallback((line: string) => {
    const el = region.current;
    if (!el || !line) return;
    if (together.current) { if (!together.current.includes(line)) together.current.push(line); }
    else {
      together.current = [line];
      queueMicrotask(() => { together.current = null; });
    }
    const text = together.current.join(' ');
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

/** The words a screen reader would read in `el`: its text, without what is hidden from it, in one line. */
export function heard(el: Element | null): string {
  if (!el) return '';
  const parts: string[] = [];
  const walk = (n: Node) => {
    if (n.nodeType === Node.TEXT_NODE) { parts.push(n.textContent ?? ''); return; }
    if (n instanceof Element && (n.getAttribute('aria-hidden') === 'true' || n.hasAttribute('hidden'))) return;
    // A line break, and a part laid out on its own (a paragraph, a label set as a block), part its words from what is
    // on either side: "Accounts without a type" and the line under it are not run together. Inline parts (a bold name)
    // join the words around them.
    if (n instanceof HTMLBRElement) { parts.push(' '); return; }
    const own = n instanceof HTMLElement && n !== el && !getComputedStyle(n).display.startsWith('inline');
    if (own) parts.push(' ');
    for (const c of n.childNodes) walk(c);
    if (own) parts.push(' ');
  };
  walk(el);
  return parts.join('').replace(/\s+/g, ' ').trim();
}

/** Issue #23: says what `el` shows through the polite region when it appears and whenever its words change, so a
 *  visible line (a notice, Review's caught-up state) is heard without being a live region added with its text. */
export function useSayShown(el: RefObject<HTMLElement | null>, on = true) {
  const live = useLive();
  const said = useRef('');
  // The text last looked at. This runs after every render and heard() reads each part's style, so heard() runs only
  // when the text has changed.
  const seen = useRef('');
  useEffect(() => {
    if (!on || !live) return;
    const raw = el.current?.textContent ?? '';
    if (raw === seen.current) return;
    seen.current = raw;
    const text = heard(el.current);
    if (!text || text === said.current) return;
    said.current = text;
    live.say(text);
  });
}
