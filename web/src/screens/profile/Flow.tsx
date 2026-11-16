import { ArrowLeft } from 'lucide-react';
import { useCallback, useRef, useState, useSyncExternalStore } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { ApiError } from '../../api/client';
import { answerSection, refreshProfile, setResume, type ProfileState } from '../../api/profile';
import { Link, useNavigate } from '../../book/links';
import { useFocusOnMount } from '../../lib/focus';
import { SECTION_NAME, sectionPath, type SectionKey } from '../../lib/profileSections';
import { Button } from '../../ui/Button';
import { Notice } from '../../ui/Notice';
import { StepBar } from '../../ui/StepBar';
import { failure } from '../settings/shared';
import { BACK, DONE, NEXT, PLAN, SKIP, STEP_N_OF, TITLE } from './copy';
import { FieldCtx, invalidateProfile, type Flusher } from './field';
import { useOffer } from './home/offer';
import type { SectionDef } from './sections';

export type Finished = { finished: SectionKey | null; allDone: boolean };

/** /profile/{section}/{step}: one step of the section's guided flow (spec, The guided flow). */
export function Flow({ section, def, step, profile }: { section: SectionKey; def: SectionDef; step: string; profile: ProfileState }) {
  const nav = useNavigate();
  const qc = useQueryClient();
  const [params] = useSearchParams();
  const fromPlan = params.get('from') === 'plan';
  const from = fromPlan ? ('plan' as const) : undefined;
  const titleRef = useFocusOnMount<HTMLHeadingElement>();
  const flushers = useRef(new Set<Flusher>());
  const { offer, view: undoView } = useOffer();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const register = useCallback((f: Flusher) => { flushers.current.add(f); return () => { flushers.current.delete(f); }; }, []);
  const i = def.steps.findIndex((s) => s.key === step);
  const cur = def.steps[i];
  const stepAt = (from: number, dir: 1 | -1): number => {
    let j = from + dir;
    while (j >= 0 && j < def.steps.length && def.steps[j].skip?.(qc)) j += dir;
    return j;
  };
  // A step's skip reads the cache (Home and cars' answer), so the flow re-renders when a flag flips.
  useSyncExternalStore((on) => qc.getQueryCache().subscribe(on), () => def.steps.map((s) => (s.skip?.(qc) ? '1' : '0')).join(''));
  const nextIndex = stepAt(i, 1);
  const prevIndex = stepAt(i, -1);
  const last = nextIndex >= def.steps.length;
  const home = fromPlan ? '/plan' : '/profile';

  const flush = async () => (await Promise.all([...flushers.current].map((f) => f()))).every(Boolean);

  async function run(fn: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try { await fn(); } catch (e) { setError(failure(e)); } finally { setBusy(false); }
  }
  const forward = () => run(async () => {
    if (!(await flush())) return;                         // a save failed: its words are under the field, Next waits
    const ahead = stepAt(i, 1);                           // the save may have changed which steps are skipped
    if (ahead >= def.steps.length) { await finish(false); return; }
    const to = def.steps[ahead].key;
    await refreshProfile(qc, setResume(section, to));
    nav(sectionPath(section, to, from));
  });
  const finish = (skip: boolean) => run(async () => {
    if (!skip && !(await flush())) return;
    if (!skip && cur.beforeDone) {
      const made = await cur.beforeDone(profile);
      if (made) { await invalidateProfile(qc); offer(made.text, made.token); return; }   // nothing vanishes unseen: stay one press, Done again leaves
    }
    let state: ProfileState;
    try {
      state = await answerSection(section, skip ? 'skipped' : 'done');
    } catch (e) {
      if (!(e instanceof ApiError) || e.status !== 409) throw e;
      state = await answerSection(section, 'skipped');   // data not complete: Skipped, and the row says what's missing
    }
    await refreshProfile(qc, Promise.resolve(state));
    const done = state.sections.find((s) => s.key === section)?.status === 'done';
    nav(home, { state: { finished: done ? section : null, allDone: state.finished } satisfies Finished });
  });
  const skip = () => (last ? finish(true) : run(async () => {
    const to = def.steps[nextIndex].key;
    await refreshProfile(qc, setResume(section, to));
    nav(sectionPath(section, to, from));
  }));

  return (
    <FieldCtx.Provider value={{ mode: 'flow', register, canEdit: true }}>
      <div className="screen profile prof-flow">
        <header className="prof-flow__head">
          <Link className="link" to={home}><ArrowLeft className="i" size={20} aria-hidden="true" />{fromPlan ? PLAN : TITLE}</Link>
          <h1 ref={titleRef} tabIndex={-1}>{SECTION_NAME[section]}</h1>
          <StepBar label={STEP_N_OF.replace('{n}', String(i + 1)).replace('{m}', String(def.steps.length))} current={step}
            states={def.steps.map((s, j) => ({ key: s.key, status: j < i ? 'done' : 'todo' }))} />
        </header>
        <section className="prof-step" aria-labelledby="prof-step-h">
          <h2 id="prof-step-h">{cur.title(profile.names, profile)}</h2>
          <cur.Body profile={profile} />
        </section>
        {error && <Notice tone="error">{error}</Notice>}
        {undoView}
        <div className="prof-foot">
          {prevIndex >= 0 && <Link className="btn btn--quiet" to={sectionPath(section, def.steps[prevIndex].key, from)}>{BACK}</Link>}
          <button type="button" className="link" disabled={busy} onClick={() => void skip()}>{SKIP}</button>
          <Button busy={busy} onClick={() => void (last ? finish(false) : forward())}>{last ? DONE : NEXT}</Button>
        </div>
      </div>
    </FieldCtx.Provider>
  );
}
