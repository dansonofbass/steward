import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { ApiError } from '../../api/client';
import { useFacts } from '../../api/hooks';
import { Notice } from '../../ui/Notice';
import { useChildren, type LeverField, type LeverKey, type LeverValue, type PlanReady } from './api';
import { BusinessRangeLine } from './BusinessRangeLine';
import { LeverList } from './LeverList';
import { EMPTY_DRAFT, afterSave, trySuggestion, turnOnCompanions, unpinLever, withAssumed, withTry, type Draft, type RowCtx } from './levers';
import { peopleFrom } from './people';
import { LastSavedAges, lastSavedOf } from './PlanFailed';
import { SaveBar } from './SaveBar';
import { TryBar } from './TryBar';
import { usePlanDraft } from './usePlanDraft';
import { usePlanSave } from './usePlanSave';
import { thisYear } from '../../lib/today';

/** Try changes (plan subpages decision 3): today's "What would change it" as a simulator. The levers keep their
 *  behaviour (assumed versus try, pinned suggestions, impacts ranked once then frozen, the 150 ms debounce). The
 *  Comfortably age and the headline sit in a pinned bar. No chart, Big costs, Next dollar, tax mix or net worth, so a
 *  preview re-renders only the bar and the lever rows. */
export function TryChanges({ data }: { data: PlanReady }) {
  const qc = useQueryClient();
  const facts = useFacts();
  const kids = useChildren();
  const planYear = data.result.band[0]?.year ?? thisYear();
  const people = peopleFrom(data.names, facts.data?.facts, planYear, data.result.band[0]?.jr_age ?? 40);
  const ctx: RowCtx = { ...people, childLabels: (kids.data?.children ?? []).map((c) => c.label), college: data.inputs.college };
  const live = usePlanDraft(data);
  const saver = usePlanSave(data, people.names.jr);
  const [epoch, setEpoch] = useState(0);
  const [pinned, setPinned] = useState(false);

  // A 409 means setup is unfinished again: refetch the plan, and Plan shows the checklist.
  useEffect(() => {
    if (live.error instanceof ApiError && live.error.status === 409) void qc.invalidateQueries({ queryKey: ['plan'] });
  }, [live.error, qc]);
  const failure = live.error && !(live.error instanceof ApiError && live.error.status === 409) ? live.error : null;
  const last = lastSavedOf(failure);
  const pending = live.resultPending && !live.error;

  function change(fn: (d: Draft) => Draft) {
    live.setDraft(fn);
    saver.clear();
  }
  const onAssumed = (field: LeverField, v: LeverValue) => change((d) => {
    let next = withAssumed(d, field, v);
    for (const [f, val] of Object.entries(turnOnCompanions(field, v, live.shown.assumed, live.shown.try))) next = withAssumed(next, f as LeverField, val as LeverValue);
    return next;
  });
  const onTry = (field: LeverField, v: LeverValue) => change((d) => withTry(d, field, v));
  const onTryThis = (key: LeverKey) => change((d) => trySuggestion(d, key, live.shown.try));
  const onUnpin = (key: LeverKey) => change((d) => unpinLever(d, key));

  async function save() {
    const sent = live.draft;
    const res = await saver.save(live.body);
    if (!res) return;
    // Moves made while the save was in flight stay in the draft; only the saved levers are cleared.
    live.setDraft((d) => afterSave(d, sent));
    setEpoch((e) => e + 1);
  }
  function reset() {
    live.setDraft(EMPTY_DRAFT);
    saver.clear();
    setEpoch((e) => e + 1);
  }

  return (
    <div className={`plan plan-try${pinned ? ' plan--savebar' : ''}`}>
      <TryBar result={live.result} was={live.was} pending={pending} basisCents={data.inputs.spending_basis_cents} spendingPct={live.shown.assumed.spending_pct} />
      {failure && (
        <div className="stack">
          <Notice tone="error"><p>{(failure as Error).message}</p></Notice>
          {last && <LastSavedAges last={last} />}
        </div>
      )}
      <SaveBar plan={data.plan} dirty={live.dirty} busy={saver.saving} error={saver.error} note={saver.note} onSave={save} onReset={reset} onPinned={setPinned} />
      {data.business && <BusinessRangeLine range={data.business} />}
      <LeverList specs={data.lever_specs} server={data.levers} live={live} ctx={ctx} epoch={epoch}
        onAssumed={onAssumed} onTry={onTry} onTryThis={onTryThis} onUnpin={onUnpin} />
    </div>
  );
}
