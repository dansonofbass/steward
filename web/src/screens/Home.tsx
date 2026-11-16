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
import { Verdict } from './home/Verdict';
import './home.css';

// Secondary parts load in their own chunks once Home is ready (Home spec, Performance).
const MonthStrip = lazyScreen(() => import('./home/MonthStrip'));
const HomeSince = lazyScreen(() => import('./home/HomeSince'));

/** Home (phase 11 spec): How are we doing?, then For you, then Since you last looked, then the day-to-day accounts.
 *  The ready mark covers /api/home and /api/accounts only (P38); everything after it is secondary and never blocks it. */
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
      {live && ready && <Suspense fallback={null}><MonthStrip months={data.flow.months} asOf={data.as_of} /></Suspense>}
      {data && <ForYou data={data} ready={ready} />}
      {ready && data?.since && <Suspense fallback={null}><HomeSince since={data.since} asOf={data.as_of} /></Suspense>}
      <AccountGroups accounts={accounts.data?.accounts} />
      {ready && <Suspense fallback={null}><HomeTree /></Suspense>}
    </div>
  );
}

export default Home;
