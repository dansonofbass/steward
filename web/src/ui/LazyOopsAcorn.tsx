import { Suspense } from 'react';
import { lazyScreen } from '../lib/lazyScreen';

const Oops = lazyScreen(() => import('./OopsAcorn').then((m) => ({ default: m.OopsAcorn })));

/** OopsAcorn for the screens in the initial bundle (Home): the face, its rules and its motion load on demand, and
 *  nothing shows while they do. */
export function LazyOopsAcorn({ size }: { size?: number }) {
  return <Suspense fallback={null}><Oops size={size} /></Suspense>;
}
