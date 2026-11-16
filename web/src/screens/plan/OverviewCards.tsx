import { useQuery } from '@tanstack/react-query';
import { ChevronRight } from 'lucide-react';
import { Link } from '../../book/links';
import { Notice } from '../../ui/Notice';
import { Skeleton } from '../../ui/Skeleton';
import { postImpacts, useNextDollar, type Impact, type NextStep, type PlanReady } from './api';
import { HELP_MOST, HELP_MOST_LINK, NEXT_DOLLAR_CARD, NEXT_STEP_LINK, NOTHING_HELPS } from './copy';
import { effectClass } from './levers';

/** The levers that bring the Comfortably age earliest, in the server's order (largest effect first), one row per lever
 *  (college has a row per child; the first counts). Only rows that help: a later age is not "help". */
export function topHelps(impacts: Impact[], n = 2): Impact[] {
  const out: Impact[] = [];
  for (const i of impacts) {
    if (out.length === n) break;
    if (effectClass(i) === 'is-earlier' && !out.some((o) => o.key === i.key)) out.push(i);
  }
  return out;
}

/** Where the next dollar goes now: the first step that isn't done, numbered as on its page; the last when all are. */
export function currentStep(steps: NextStep[]): { step: NextStep; n: number } | null {
  if (steps.length === 0) return null;
  const i = steps.findIndex((s) => s.status !== 'done');
  const at = i < 0 ? steps.length - 1 : i;
  return { step: steps[at], n: at + 1 };
}

/** The saved levers' impacts. The key changes with the saved plan and its inputs; the server caches the answer too. */
export const usePlanImpacts = (data: PlanReady) => useQuery({
  queryKey: ['plan-impacts', `${data.plan?.id ?? 0}:${data.result.input_digest}`],
  queryFn: ({ signal }) => postImpacts({}, signal),
  staleTime: Infinity,
});

/** Plan subpages decision 2: "What would help most" (linking to Try changes) and "Your next dollar" (to Next dollar). */
export function OverviewCards({ data }: { data: PlanReady }) {
  const impacts = usePlanImpacts(data);
  const nd = useNextDollar();
  const helps = impacts.data ? topHelps(impacts.data.impacts) : [];
  const now = nd.data ? currentStep(nd.data.steps) : null;
  return (
    <div className="grid-cards plan-cards">
      <section className="card plan-card" aria-labelledby="help-h" data-testid="help-card">
        <h2 id="help-h">{HELP_MOST}</h2>
        {impacts.isError ? <Notice tone="error">{impacts.error.message}</Notice>
          : !impacts.data ? <Skeleton lines={2} />
            : helps.length === 0 ? <p className="muted">{NOTHING_HELPS}</p> : (
              <ul className="plan-card__list">
                {helps.map((i) => <li key={i.key}><span className="plan-card__name">{i.label}</span><span className="plan-card__effect">{i.text}</span></li>)}
              </ul>
            )}
        <Link className="link plan-card__link" to="/plan/try">{HELP_MOST_LINK}<ChevronRight className="i" size={16} aria-hidden="true" /></Link>
      </section>
      <section className="card plan-card" aria-labelledby="next-h" data-testid="next-card">
        <h2 id="next-h">{NEXT_DOLLAR_CARD}</h2>
        {nd.isError ? <Notice tone="error">{nd.error.message}</Notice> : !nd.data ? <Skeleton lines={2} /> : now && (
          <>
            <p className="plan-card__step"><span className="nd__n">{now.n}</span><span className="plan-card__name">{now.step.title}</span></p>
            <p className="small muted">{now.step.why}</p>
          </>
        )}
        <Link className="link plan-card__link" to="/plan/next">{NEXT_STEP_LINK}<ChevronRight className="i" size={16} aria-hidden="true" /></Link>
      </section>
    </div>
  );
}
