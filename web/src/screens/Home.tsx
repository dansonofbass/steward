import { Suspense, useEffect, useRef } from 'react';
import { useLocation } from 'react-router-dom';
import { useHome } from '../api/home';
import { useAccounts, useBusiness } from '../api/hooks';
import { JOINED_BOOK, TRY_AGAIN } from '../lib/copy';
import { lazyScreen } from '../lib/lazyScreen';
import { Button } from '../ui/Button';
import { Notice } from '../ui/Notice';
import { AccountGroups } from './home/AccountGroups';
import { HomeTree } from './home/lazyMoments';
import { GatewayOffLine } from './home/GatewayOffLine';
import { ForYou } from './home/ForYou';
import { Signs } from './home/Signs';
import { useHomeVisit } from './home/useHomeVisit';
import { SinceRoom, StripRoom } from './home/rooms';
import { Verdict } from './home/Verdict';
import './home.css';

// Secondary parts are their own chunks (Home spec, Performance). Issue #24: they start loading as the address is
// reached, beside /api/home (routes.tsx, HOME_WARM), and an empty room of their shape holds each place until its chunk
// lands, so nothing below them moves.
const MonthStrip = lazyScreen(() => import('./home/MonthStrip'));
const HomeSince = lazyScreen(() => import('./home/HomeSince'));
export const preloadHomeParts = () => Promise.all([MonthStrip.preload(), HomeSince.preload()]);

/** Home (phase 11 spec): How are we doing?, then For you, then Since you last looked, then the day-to-day accounts.
 *  The ready mark covers /api/home and /api/accounts only (P38); everything after it is secondary and never blocks it.
 *  Nothing shows under the verdict until /api/home answers: a placeholder there would be pushed down the screen when
 *  the signs and For you land (issue #24). */
export function Home() {
  const joined = (useLocation().state as { joined?: string } | null)?.joined;
  const home = useHome();
  const accounts = useAccounts();
  const ready = home.isSuccess && accounts.isSuccess;
  const data = home.data;
  // P15: only once Home is ready, and only for a household with a business.
  const business = useBusiness(null, ready && data?.signs.has_business === true);
  useHomeVisit(ready ? data?.mark : undefined);
  const marked = useRef(false);
  useEffect(() => {
    if (ready && !marked.current) {
      marked.current = true;
      performance.mark('home-ready');
    }
  }, [ready]);

  const failed = [home, accounts].filter((q) => q.isError);
  if (failed.length > 0) {
    return (
      <div className="screen home">
        <Notice tone="error">
          <p>{failed[0].error?.message}</p>
          <Button variant="quiet" onClick={() => failed.forEach((q) => void q.refetch())}>{TRY_AGAIN}</Button>
        </Notice>
      </div>
    );
  }
  const live = data !== undefined && data.verdict.opener !== 'empty';
  return (
    <div className="screen home">
      {joined && <Notice>{JOINED_BOOK.replace('{name}', joined)}</Notice>}
      <GatewayOffLine />
      <Verdict data={data} ready={ready} />
      {live && <Signs signs={data.signs} month={data.month} business={business.data} businessFailed={business.isError} />}
      {live && data.flow.months.length > 0 && <Suspense fallback={<StripRoom />}><MonthStrip months={data.flow.months} asOf={data.as_of} /></Suspense>}
      {data && <ForYou data={data} ready={ready} />}
      {data?.since && <Suspense fallback={<SinceRoom since={data.since} asOf={data.as_of} />}><HomeSince since={data.since} asOf={data.as_of} /></Suspense>}
      {data && <AccountGroups accounts={accounts.data?.accounts} />}
      {ready && data && <Suspense fallback={null}><HomeTree asOf={data.as_of} /></Suspense>}
    </div>
  );
}

export default Home;
