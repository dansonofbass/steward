import { useEffect, useRef } from 'react';
import { seeHome } from '../../api/home';

/** P27: 10 seconds on screen and visible is a full look. */
export const LOOK_MS = 10_000;

/** A visit (Home spec P27, P28). Once Home is ready (a mark is given), one glance; after 10 s of visible time in this
 *  mount, one full look. Hidden time doesn't count: one visibilitychange listener while mounted, no polling. Each
 *  sends the newest mark the server gave. A refused look (a mark older than a day) is silent: nothing on Home
 *  depends on it. */
export function useHomeVisit(mark: string | undefined): void {
  const latest = useRef(mark);
  latest.current = mark;
  const started = mark !== undefined;
  useEffect(() => {
    if (!started) return undefined;
    const send = (glance: boolean) => { if (latest.current) seeHome(latest.current, glance).catch(() => undefined); };
    send(true);
    let left = LOOK_MS;
    let since = 0;
    let timer: number | undefined;
    function onChange() {
      if (document.visibilityState === 'visible') start();
      else stop();
    }
    function start() {
      if (timer !== undefined || left <= 0) return;
      since = Date.now();
      timer = window.setTimeout(() => {
        timer = undefined;
        left = 0;
        document.removeEventListener('visibilitychange', onChange);
        send(false);
      }, left);
    }
    function stop() {
      if (timer === undefined) return;
      window.clearTimeout(timer);
      timer = undefined;
      left -= Date.now() - since;
    }
    document.addEventListener('visibilitychange', onChange);
    onChange();
    return () => { stop(); document.removeEventListener('visibilitychange', onChange); };
  }, [started]);
}
