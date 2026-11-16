import { Suspense } from 'react';
import { Outlet, useLocation, useOutletContext } from 'react-router-dom';
import { usePlanQuery } from '../api/hooks';
import { NotAdvice } from '../ui/NotAdvice';
import { Skeleton } from '../ui/Skeleton';
import { isReady, type PlanReady, type PlanResponse } from './plan/api';
import { PLAN_TITLE } from './plan/copy';
import { HowItWorks } from './plan/HowItWorks';
import { NextDollar } from './plan/NextDollar';
import { Overview } from './plan/Overview';
import { PlanFailed } from './plan/PlanFailed';
import { PlanTabs, tabOf } from './plan/PlanTabs';
import { TryChanges } from './plan/TryChanges';
import { Setup } from './plan/Setup';
import './plan/plan.css';

/** The Plan tab (plan subpages): the row of pages, and the plan fetched once and handed to whichever page is open.
 *  Loaded on demand with its pages (routes.tsx); everything they need lives under screens/plan/. While setup is
 *  unfinished every address here shows the checklist. */
export default function Plan() {
  const q = usePlanQuery<PlanResponse>();
  const { pathname } = useLocation();
  const ready = q.data === undefined || isReady(q.data);
  const tabs = <PlanTabs on={ready ? tabOf(pathname) : 'overview'} ready={ready} />;
  if (q.isPending) return <div className="screen plan-screen" aria-busy="true">{tabs}<Skeleton lines={6} /></div>;
  if (q.isError) return <div className="screen plan-screen">{tabs}<PlanFailed error={q.error} onRetry={() => q.refetch()} /></div>;
  if (!isReady(q.data)) return <div className="screen plan-screen">{tabs}<Setup /><NotAdvice /></div>;
  return (
    <div className="screen plan-screen">
      {tabs}
      <h1 className="sr-only">{PLAN_TITLE}</h1>
      <Suspense fallback={<Skeleton lines={6} />}><Outlet context={q.data} /></Suspense>
      <NotAdvice />
    </div>
  );
}

const usePlanData = () => useOutletContext<PlanReady>();

export function OverviewRoute() { return <Overview data={usePlanData()} />; }
export function TryRoute() { return <TryChanges data={usePlanData()} />; }
export function NextRoute() { return <NextDollar />; }
export function HowRoute() { return <HowItWorks data={usePlanData()} />; }
