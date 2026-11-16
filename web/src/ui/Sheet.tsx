import { X } from 'lucide-react';
import { createContext, useCallback, useContext, useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode, type RefObject } from 'react';
import { createPortal } from 'react-dom';
import { CLOSE, DISCARD, DISCARD_ASK, KEEP_EDITING } from '../lib/copy';
import { Button } from './Button';
import { LiveRegions } from './Live';
import './Sheet.css';

type Props = { open: boolean; onClose: () => void; title: string; children: ReactNode; inline?: boolean;
  focusRef?: RefObject<HTMLElement | null>; className?: string;
  /** Where focus goes when it closes; what had focus when it opened, by default. */
  returnTo?: () => HTMLElement | null;
  /** A close request (Escape, the back gesture, a tap outside) comes here first; true means it was handled and the sheet
   *  stays open (Ask's first-use tip). */
  onEscape?: () => boolean;
  /** The caller keeps what was typed when the sheet closes (Ask's panel resumes it), so closing asks nothing. */
  keepsDraft?: boolean };

/** The boxes whose typing a close would lose, dates and times among them. A search or a combobox (CategoryMenu's find
 *  box) holds no draft, and neither does a read-only box. */
const DRAFT_BOXES = 'textarea, input:not([type]), input[type="text"], input[type="email"], input[type="number"], input[type="password"], input[type="tel"], input[type="url"], input[type="date"], input[type="month"], input[type="time"], input[type="datetime-local"], input[type="week"]';
const isDraftBox = (el: EventTarget | null): el is HTMLInputElement | HTMLTextAreaElement =>
  el instanceof Element && el.matches(DRAFT_BOXES) && !el.matches('[readonly], [role="combobox"]');

/** A form in a sheet that saves without closing tells the sheet what it now holds is saved (16i review I-2). */
const SavedCtx = createContext<((scope: Element) => void) | null>(null);

/** For a form that saves in place inside a sheet (a transaction's merchant, its note's name): pass a ref to the form, and
 *  call the function after a save succeeds, never after one fails. Once the form has rendered what it saved, the sheet
 *  takes that form's boxes as the new baseline, and only that form's: another form in the same sheet keeps asking about
 *  its own unsaved text (16i re-review R-1). Outside a sheet it does nothing. savedInPlace.test.ts scans for sheet forms
 *  that save and stay open without it, without a scope, or without calling it. */
export function useSheetSaved(scope: RefObject<Element | null>): () => void {
  const rebaseline = useContext(SavedCtx);
  const [saves, setSaves] = useState(0);
  useLayoutEffect(() => {
    const el = scope.current;
    if (saves && el) rebaseline?.(el);
  }, [saves, rebaseline, scope]);
  return useCallback(() => setSaves((n) => n + 1), []);
}

/** Whether a pointer event is outside the sheet's box: a tap on the backdrop targets the <dialog> itself. Position, not
 *  target alone, since the sheet's own padding targets it too. */
function outside(e: PointerEvent, d: HTMLDialogElement): boolean {
  if (e.target !== d) return false;
  const r = d.getBoundingClientRect();
  return e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom;
}

/** Bottom sheet on phones, side panel from 900 px: a modal <dialog> (WEB-1). showModal() gives it the top layer, an inert
 *  page behind, focus kept inside, focus back to the opener when it closes, and the platform's close requests: Escape,
 *  and Android's back gesture, which closes the sheet instead of leaving the page.
 *
 *  One rule for every way out that isn't the sheet's own Save or Cancel (Close, Escape, back, a tap outside): with typed
 *  text in it, the sheet asks before it discards it. Asked again (a second Escape, back press or tap outside) it stays
 *  open. Chrome and Edge won't let a second Escape or back press be stopped without a tap in between: the dialog closes,
 *  and the sheet opens it again with the question still showing. A third one in a row does close it, so a person is
 *  never trapped (the browser's reason for its rule); that is a discard.
 *
 *  `inline` is a static preview for the /design page. A modal sheet renders into the page body, so no ancestor's
 *  display or stacking can hide it. */
export function Sheet({ open, onClose, title, children, inline = false, focusRef, className, returnTo, onEscape, keepsDraft = false }: Props) {
  const dialog = useRef<HTMLDialogElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const keep = useRef<HTMLButtonElement>(null);
  const handlers = useRef({ onClose, onEscape, returnTo });
  handlers.current = { onClose, onEscape, returnTo };

  const titleId = useId();
  const askId = useId();
  const modal = open && !inline;
  const [asking, setAsking] = useState(false);
  const askingNow = useRef(false);
  askingNow.current = asking;
  /** What each text box held when focus first reached it, or when its form last saved, since this opening. */
  const firstSeen = useRef(new WeakMap<Element, string>());
  /** Where focus goes back to after Keep editing. */
  const resume = useRef<HTMLElement | null>(null);
  /** Set while Sheet closes the dialog itself, so its close event isn't taken for the browser's. */
  const closing = useRef(false);
  /** The last cancel couldn't be prevented: the close that follows is the browser's, not the person's choice. */
  const forced = useRef(false);
  /** The sheet was opened again once after a forced close; the next forced close lets the person out. */
  const rescued = useRef(false);
  /** Counts the times the browser closed it on its own (see the close listener). */
  const [reshow, setReshow] = useState(0);

  const typed = () => {
    const d = dialog.current;
    if (!d || keepsDraft) return false;
    return [...d.querySelectorAll(DRAFT_BOXES)].some((el) => isDraftBox(el) && firstSeen.current.has(el) && el.value !== firstSeen.current.get(el));
  };
  const ask = () => {
    resume.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setAsking(true);
  };
  /** Close, unless there's typed text to ask about. */
  const leave = () => {
    if (typed()) ask();
    else handlers.current.onClose();
  };
  const actions = useRef({ leave });
  actions.current = { leave };
  const rebaseline = useCallback((scope: Element) => {
    if (!dialog.current?.contains(scope)) return;
    for (const el of scope.querySelectorAll(DRAFT_BOXES)) if (isDraftBox(el)) firstSeen.current.set(el, el.value);
  }, []);

  useLayoutEffect(() => {
    const d = dialog.current;
    if (!modal || !d) return;
    closing.current = false;
    forced.current = false;
    rescued.current = false;
    firstSeen.current = new WeakMap();
    setAsking(false);
    const onFocusIn = (e: FocusEvent) => {
      if (isDraftBox(e.target) && !firstSeen.current.has(e.target)) firstSeen.current.set(e.target, e.target.value);
    };
    // A tap or a typed key is a user activation: the browser lets the next close request be stopped again.
    const onActive = () => { rescued.current = false; };
    // Escape, the back gesture, and (with closedby="any") a tap outside.
    const closeRequest = () => {
      if (askingNow.current) { setAsking(false); return; }   // asked again: Keep editing
      if (handlers.current.onEscape?.()) return;
      actions.current.leave();
    };
    const onCancel = (e: Event) => {
      if (e.target !== d) return;
      // Chrome and Edge: a second Escape or back press with no tap in between can't be stopped. The dialog closes next;
      // the close listener decides what that means.
      if (!e.cancelable) { forced.current = true; return; }
      // A cancel that can be stopped means the browser saw an activation since the last one (a key that pressed a button
      // counts, with no pointerdown or input): the next forced close is caught again (16i re-review R-2).
      rescued.current = false;
      e.preventDefault();
      closeRequest();
    };
    const onNativeClose = () => {
      if (closing.current) return;
      const wasForced = forced.current;
      forced.current = false;
      if (wasForced && !rescued.current && typed()) {
        // Typed text would be lost by a close nobody chose: open it again, asking (16i review I-1).
        rescued.current = true;
        if (!askingNow.current) resume.current = null;
        setAsking(true);
        setReshow((n) => n + 1);
        return;
      }
      setAsking(false);
      handlers.current.onClose();
      setReshow((n) => n + 1);   // a parent that keeps it open gets it shown again
    };
    // Where closedby isn't supported (Safari), a tap outside is found by hand: pressed and released outside, so a text
    // selection dragged out of the sheet doesn't close it.
    let pressedOutside = false;
    const byHand = !('closedBy' in HTMLDialogElement.prototype);
    const onDown = (e: PointerEvent) => { pressedOutside = outside(e, d); };
    const onUp = (e: PointerEvent) => {
      if (!pressedOutside || !outside(e, d)) return;
      pressedOutside = false;
      closeRequest();
    };
    d.addEventListener('focusin', onFocusIn);
    d.addEventListener('pointerdown', onActive);
    d.addEventListener('input', onActive);
    d.addEventListener('cancel', onCancel);
    d.addEventListener('close', onNativeClose);
    if (byHand) { d.addEventListener('pointerdown', onDown); d.addEventListener('pointerup', onUp); }
    if (!d.open) d.showModal();
    return () => {
      d.removeEventListener('focusin', onFocusIn);
      d.removeEventListener('pointerdown', onActive);
      d.removeEventListener('input', onActive);
      d.removeEventListener('cancel', onCancel);
      d.removeEventListener('close', onNativeClose);
      d.removeEventListener('pointerdown', onDown);
      d.removeEventListener('pointerup', onUp);
      closing.current = true;
      if (d.open) d.close();   // the browser gives focus back to what had it when the sheet opened
    };
  }, [modal]);

  // returnTo is asked once the commit that closed the sheet is done: what it names may arrive in that same commit (Pair
  // again's form, which replaces the button that opened the sheet).
  useEffect(() => {
    if (!modal) return;
    return () => { handlers.current.returnTo?.()?.focus(); };
  }, [modal]);

  useLayoutEffect(() => {
    const d = dialog.current;
    if (modal && d && reshow > 0 && !d.open) d.showModal();
  }, [modal, reshow]);

  useLayoutEffect(() => {
    if (!modal) return;
    if (askingNow.current) { keep.current?.focus(); return; }   // opened again over a forced close: still asking
    const target = focusRef?.current ?? null;
    target?.focus();                                   // CategoryMenu: you're typing as soon as it opens
    if (!target || document.activeElement !== target) heading.current?.focus();      // a disabled box can't take it
  }, [modal, focusRef, reshow]);

  const asked = useRef(false);
  useLayoutEffect(() => {
    if (asking) { asked.current = true; keep.current?.focus(); return; }
    if (!asked.current) return;
    asked.current = false;
    const back = resume.current;
    resume.current = null;
    (back?.isConnected && dialog.current?.contains(back) ? back : heading.current)?.focus();
  }, [asking]);

  if (!open) return null;

  // The question takes the head's place (Sheet.css). Focus starts on Keep editing, the safe answer, which reads the
  // question as its description; Discard never lands where Close was.
  const head = (
    <div className={`sheet__head${asking ? ' is-asking' : ''}`}>
      <h2 id={titleId} ref={heading} tabIndex={-1} className="sheet__title">{title}</h2>
      <Button variant="quiet" icon={X} onClick={inline ? onClose : () => actions.current.leave()}>{CLOSE}</Button>
      {asking && (
        <div className="sheet__ask">
          <p id={askId} className="sheet__ask-q">{DISCARD_ASK}</p>
          <div className="sheet__ask-acts">
            <Button variant="danger" onClick={() => { setAsking(false); resume.current = null; handlers.current.onClose(); }}>{DISCARD}</Button>
            <Button ref={keep} variant="quiet" aria-describedby={askId} onClick={() => setAsking(false)}>{KEEP_EDITING}</Button>
          </div>
        </div>
      )}
    </div>
  );
  if (inline) {
    return (
      <section className={`sheet sheet--inline${className ? ` ${className}` : ''}`} aria-labelledby={titleId}>
        {head}
        <div className="sheet__body">{children}</div>
      </section>
    );
  }
  return createPortal(
    // closedby="any": a tap outside is a close request too (Chrome, Edge, Firefox). The attribute isn't in React's types yet.
    // Its own live regions (WEB-7): the page behind a modal is inert, so a toast or a line said there would go unheard.
    <dialog ref={dialog} className={`sheet${className ? ` ${className}` : ''}`} aria-labelledby={titleId} {...{ closedby: 'any' }}>
      <SavedCtx.Provider value={rebaseline}>
        <LiveRegions>
          {head}
          <div className="sheet__body">{children}</div>
        </LiveRegions>
      </SavedCtx.Provider>
    </dialog>,
    document.body,
  );
}
