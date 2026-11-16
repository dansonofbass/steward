// One Ask about this panel per book (P3), in BookScope: nothing until the first open, then the lazy panel, which stays
// mounted while closed. Until its chunk arrives, the Sheet's frame and title show at once with a skeleton. A route
// change closes the panel; switching books (a new key) drops it.
import { Suspense, useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import { ASK } from '../lib/copy';
import { Sheet } from '../ui/Sheet';
import { Skeleton } from '../ui/Skeleton';
import { focusBack } from './focus';
import { AskPanel } from './panel';
import { askState, closeAsk, resetAsk, useAskState } from './store';

export function AskHost() {
  const s = useAskState();
  const { pathname } = useLocation();
  useEffect(() => { closeAsk(); }, [pathname]);
  useEffect(() => () => { resetAsk(); }, []);
  if (!s.mounted) return null;
  const frame = s.open
    ? <Sheet open onClose={closeAsk} title={ASK} returnTo={() => focusBack(askState().opener)}><Skeleton lines={3} /></Sheet>
    : null;
  return <Suspense fallback={frame}><AskPanel /></Suspense>;
}
