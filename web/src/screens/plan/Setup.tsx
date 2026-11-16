import { useEffect } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useCanEdit } from '../../book/BookContext';
import { useAccounts } from '../../api/hooks';
import { TRY_AGAIN } from '../../lib/copy';
import { PLAN_ITEM_SECTION, sectionPath } from '../../lib/profileSections';
import { Button } from '../../ui/Button';
import { ChecklistRow } from '../../ui/ChecklistRow';
import { Notice } from '../../ui/Notice';
import { Skeleton } from '../../ui/Skeleton';
import { UntypedNotice } from '../../ui/UntypedNotice';
import { useChildren, usePlanSetup, type SetupItem, type SetupKey } from './api';
import { markSetupOpen } from './PlanReady';
import {
  AUTOMATIC, GO_ADD, GO_CHECK, GO_DONE, GO_FINISH, GO_IMPORT, GO_UPLOAD, HEALTH_PREFILLED, N_OF_M_DONE, OPTIONAL,
  PLAN_TITLE, REQUIRED, SETUP_LEDE, SETUP_NOTE, SETUP_NOTE_VIEWER, STATUS_TO_DO, STAYS_HOME,
} from './copy';

/** Onboarding ruling 10: the Set up Steward order, with Spending history (automatic) at the end. */
export const SETUP_ORDER: SetupKey[] = ['household', 'mortgage', 'pay', 'children', 'health', 'earnings', 'history'];

export function orderSetup(items: SetupItem[]): { required: SetupItem[]; optional: SetupItem[] } {
  const rank = (k: SetupKey) => { const i = SETUP_ORDER.indexOf(k); return i < 0 ? SETUP_ORDER.length : i; };
  return {
    required: items.filter((i) => i.required).sort((a, b) => rank(a.key) - rank(b.key)),
    optional: items.filter((i) => !i.required),
  };
}

export function goWord(item: SetupItem, hasChildren: boolean): string {
  if (item.done) return GO_DONE;
  switch (item.key) {
    case 'earnings': case 'earnings_spouse': return GO_UPLOAD;
    case 'children': return hasChildren ? GO_FINISH : GO_ADD;
    case 'health': return GO_CHECK;
    case 'history': return GO_IMPORT;
    default: return GO_ADD;
  }
}

/** Each row opens the Profile section that answers it and comes back here; Spending history opens the import wizard. */
export function rowHref(key: SetupKey): string {
  const section = PLAN_ITEM_SECTION[key];
  return section ? sectionPath(section, null, 'plan') : '/settings/import';
}

// A viewer reads the same rows, with no way in: every step and the import are a manager's.
function Row({ item, go, canEdit }: { item: SetupItem; go: string; canEdit: boolean }) {
  const detail = item.key === 'health' && !item.done && item.suggested_cents !== null ? `${item.detail} ${HEALTH_PREFILLED}` : item.detail;
  return (
    <ChecklistRow done={item.done} status={item.done ? GO_DONE : STATUS_TO_DO} title={item.title} tag={item.key === 'history' && <span className="tag">{AUTOMATIC}</span>}
      detail={detail} go={canEdit || item.done ? go : undefined} to={canEdit ? rowHref(item.key) : undefined} testId="setup-row" />
  );
}

export function Setup() {
  const setup = usePlanSetup();
  const accounts = useAccounts();
  const kids = useChildren();
  const qc = useQueryClient();
  const canEdit = useCanEdit();

  // Every input is in: the Plan tab's GET /api/plan now answers with ages.
  useEffect(() => { if (setup.data?.ready) void qc.invalidateQueries({ queryKey: ['plan'] }); }, [setup.data?.ready, qc]);
  // Phase 17: an unfinished checklist leaves a note, so the first overview after it can say the checklist is done.
  useEffect(() => { if (setup.data && !setup.data.ready) markSetupOpen(); }, [setup.data]);

  const head = (
    <header className="stack stack--tight">
      <h1>{PLAN_TITLE}</h1>
      <p className="lede">{SETUP_LEDE}</p>
      <p className="muted">{canEdit ? SETUP_NOTE : SETUP_NOTE_VIEWER}</p>
    </header>
  );
  if (setup.isError) {
    return <div className="stack">{head}<Notice tone="error"><p>{setup.error.message}</p><Button variant="quiet" onClick={() => setup.refetch()}>{TRY_AGAIN}</Button></Notice></div>;
  }
  if (!setup.data) return <div className="stack" aria-busy="true">{head}<Skeleton lines={6} /></div>;

  const { required, optional } = orderSetup(setup.data.setup);
  const done = required.filter((i) => i.done).length;
  const hasChildren = (kids.data?.children.length ?? 0) > 0;
  return (
    <div className="stack plan-setup">
      {head}
      <div className="progress">
        <span>{N_OF_M_DONE.replace('{n}', String(done)).replace('{m}', String(required.length))}</span>
        <span className="progress__bar" aria-hidden="true"><span style={{ width: `${required.length ? (done / required.length) * 100 : 0}%` }} /></span>
      </div>
      <section className="sec" aria-labelledby="need-h">
        <h2 id="need-h" className="eyebrow">{REQUIRED}</h2>
        <div className="card setup">{required.map((i) => <Row key={i.key} item={i} go={goWord(i, hasChildren)} canEdit={canEdit} />)}</div>
      </section>
      {optional.length > 0 && (
        <section className="sec" aria-labelledby="opt-h">
          <h2 id="opt-h" className="eyebrow">{OPTIONAL}</h2>
          <div className="card setup">{optional.map((i) => <Row key={i.key} item={i} go={goWord(i, hasChildren)} canEdit={canEdit} />)}</div>
        </section>
      )}
      <UntypedNotice accounts={accounts.data?.accounts} where="plan" />
      <p className="small muted">{STAYS_HOME}</p>
    </div>
  );
}
