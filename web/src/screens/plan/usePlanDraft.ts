import { useEffect, useMemo, useRef, useState, type Dispatch, type SetStateAction } from 'react';
import { currentBook } from '../../api/book';
import { useMe } from '../../api/hooks';
import { DEBOUNCE_MS, useDebouncedRequest } from '../../lib/useDebouncedRequest';
import { postImpacts, postPreview, type DeltaBody, type Impact, type ImpactsResponse, type LeverKey, type LeverValues, type PlanReady, type PlanResult, type PreviewResponse } from './api';
import { EMPTY_DRAFT, bodyKey, changedLevers, deltaBody, isEmptyBody, shownValues, type Draft } from './levers';
import { planMemory } from './planMemory';

export type PlanLive = {
  draft: Draft; setDraft: Dispatch<SetStateAction<Draft>>;
  body: DeltaBody; dirty: boolean; changed: LeverKey[];
  shown: { assumed: LeverValues; try: LeverValues }; notes: Partial<Record<LeverKey, string>>;
  result: PlanResult; resultPending: boolean; was: PlanResult | null;
  impacts: Impact[] | undefined; impactsPending: boolean; error: unknown;
};

const mark = (name: string) => { try { performance.mark(name); } catch { /* no performance timeline */ } };
const measure = () => { try { performance.measure('plan-preview', 'plan-preview-start', 'plan-preview-done'); } catch { /* no start mark */ } };

// Unsaved moves outlive a trip to another Plan page (plan subpages, Engineering choice 11): kept here, in this tab only,
// for the saved plan they were made against. A save by anyone (a new plan id), a reload or Reset ends them. Plan ids
// are per book and a book switch or a sign-out is an in-app navigation, so the entry is keyed by book, person and plan:
// another book, or the next person to sign in on this tab, never sees this household's moves. Sign-out also forgets it
// (clearKeptDraft, in planMemory so the frame can call it without loading this chunk).
export { clearKeptDraft } from './planMemory';
export const draftKey = (userId: number, planId: number): string => `${currentBook() ?? ''}:${userId}:${planId}`;
export const keptDraft = (key: string): Draft => {
  const { kept } = planMemory;
  return kept && kept.key === key ? kept.draft : EMPTY_DRAFT;
};
export function keepDraft(key: string, draft: Draft): void {
  const empty = Object.keys(draft.assumed).length === 0 && Object.keys(draft.try).length === 0 && draft.unpin.length === 0;
  planMemory.kept = empty ? null : { key, draft };
}

/** The local draft, and the debounced, abortable preview and impacts requests for it (spec 7). */
export function usePlanDraft(data: PlanReady): PlanLive {
  const userId = useMe().data?.user.id ?? 0;
  const key = draftKey(userId, data.plan?.id ?? 0);
  const [draft, setDraft] = useState<Draft>(() => keptDraft(key));
  useEffect(() => { keepDraft(key, draft); }, [key, draft]);
  const body = useMemo(() => deltaBody(data.levers, draft), [data.levers, draft]);
  // The saved plan and its inputs: a sheet edit or a refetch changes the digest, so old answers never match.
  const base = `${data.plan?.id ?? 0}:${data.result.input_digest}`;
  const previewKey = body.assumed ? `${base}:${bodyKey({ assumed: body.assumed })}` : null;
  const impactsKey = `${base}:${bodyKey(body)}`;

  const preview = useDebouncedRequest<PreviewResponse>(previewKey === null ? null : {
    key: previewKey,
    run: (signal) => { mark('plan-preview-start'); return postPreview({ assumed: body.assumed }, signal); },
  });
  const previewHere = previewKey !== null && preview.key === previewKey && !preview.pending;
  const previewOk = previewHere && !preview.error && preview.data !== undefined;
  const settled = previewKey === null || previewHere;

  // Impacts follow the ages for the same draft (spec 7: "the UI shows it after the ages"), and wait for a pause too:
  // a drag that goes on aborts them before they are sent, so no orphaned solve competes with the next preview.
  const impacts = useDebouncedRequest<ImpactsResponse>(
    settled ? { key: impactsKey, run: (signal) => postImpacts(body, signal) } : null,
    DEBOUNCE_MS,
  );
  const impactsHere = impacts.key === impactsKey && !impacts.pending;
  const impactsOk = impactsHere && !impacts.error;

  // While a preview is pending the last answer stays up, dimmed. After a failed preview the saved answer shows, with
  // no "was", under the error notice (spec 8).
  const last = useRef<{ digest: string; result: PlanResult }>({ digest: data.result.input_digest, result: data.result });
  if (last.current.digest !== data.result.input_digest) last.current = { digest: data.result.input_digest, result: data.result };
  const failed = previewHere && !!preview.error;
  const result = previewKey === null || failed ? data.result : previewOk ? preview.data!.result : last.current.result;
  last.current.result = result;

  const shownKey = previewOk ? previewKey : null;
  useEffect(() => { if (shownKey !== null) { mark('plan-preview-done'); measure(); } }, [shownKey]);

  const latest = (impactsOk && impacts.data?.levers) || (previewOk && preview.data?.levers) || data.levers;
  const error = (previewHere && preview.error) || (impactsHere && impacts.error) || null;
  return {
    draft, setDraft, body, dirty: !isEmptyBody(body), changed: changedLevers(data.levers, draft),
    shown: shownValues(data.levers, latest, draft), notes: latest.try_notes,
    result, resultPending: previewKey !== null && !previewOk && !failed, was: previewKey !== null && !failed ? data.result : null,
    impacts: impacts.data?.impacts, impactsPending: !impactsOk, error,
  };
}
