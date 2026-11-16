// When the first-use tip shows (Ask about this P23): due for this person and What Claude will see is on screen, or
// replayed from its label. Got it and sending a question mark it done; hiding it (Escape) ends it for the rest of the
// page's life without marking it (Engineering choice 10). In the Ask tab, `escape` listens for Escape itself; the
// panel's Sheet calls hide() first instead.
import { useEffect, useState } from 'react';
import { tourDone, tourDue, tourShown } from '../../lib/askTour';

let hiddenThisLoad = false;

export function useAskTour(userId: number | null, visible: boolean, escape = false) {
  const [replay, setReplay] = useState(false);
  const [, bump] = useState(0);
  const due = userId !== null && !hiddenThisLoad && tourDue(userId);
  const show = visible && (due || replay);
  useEffect(() => { if (show) tourShown(); }, [show]);
  const hide = () => { hiddenThisLoad = true; setReplay(false); bump((n) => n + 1); };
  const done = () => { if (userId !== null) tourDone(userId); setReplay(false); bump((n) => n + 1); };
  const toggle = () => { if (show) hide(); else setReplay(true); };
  useEffect(() => {
    if (!show || !escape) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') hide(); };
    document.addEventListener('keydown', onKey);
    return () => { document.removeEventListener('keydown', onKey); };
  }, [show, escape]); // eslint-disable-line react-hooks/exhaustive-deps
  return { show, hide, done, toggle };
}

/** Tests only. */
export function resetTourHidden(): void {
  hiddenThisLoad = false;
}
