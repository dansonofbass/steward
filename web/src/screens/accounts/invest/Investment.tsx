import { Suspense, useRef, useState, type ComponentType } from 'react';
import { lazyScreen } from '../../../lib/lazyScreen';
import type { Account } from '../../../api/types';
import { useCanEdit } from '../../../book/BookContext';
import { withCelebrate } from '../../../lib/celebrations';
import { Notice } from '../../../ui/Notice';
import { Sheet } from '../../../ui/Sheet';
import { Skeleton } from '../../../ui/Skeleton';
import { AdvisoryFee } from './AdvisoryFee';
import { useInvestment } from './api';
import { ContributionsSection } from './Contributions';
import { CostAdd } from './CostAdd';
import { FIRST_IMPORT_CHEER, IMPORT_POSITIONS, IMPORT_UNAVAILABLE } from './copy';
import { Figures } from './Figures';
import { sendsLine } from './format';
import { GrowthChart } from './GrowthChart';
import { Holdings } from './Holdings';
import type { Saved } from './PositionsImport';
import './invest.css';

type ImportProps = { accountId: number; onClose: () => void; onSaved: (r: Saved) => void };
function ImportMissing({ onClose }: ImportProps) {
  return <Sheet open onClose={onClose} title={IMPORT_POSITIONS}><Notice tone="error"><p>{IMPORT_UNAVAILABLE}</p></Notice></Sheet>;
}

/** Import positions loads in its own chunk on first use; if it can't be fetched, its sheet says so. */
export const loadImport = (load: () => Promise<{ default: ComponentType<ImportProps> }> = () => import('./PositionsImport')) =>
  load().catch(() => ({ default: ImportMissing }));
const PositionsImport = lazyScreen(() => loadImport());

/** An investment account's sections (investment views spec), in their own chunk under the page's head: what the bank
 *  sends, this year's three figures, the chart, and what it's invested in with its costs. A manager can import
 *  positions, add a fund's cost and set the advisory fee. */
export default function Investment({ account }: { account: Account }) {
  const q = useInvestment(account.id);
  const canEdit = useCanEdit();
  const [importing, setImporting] = useState(false);
  const held = useRef<HTMLDivElement>(null);
  const [firstLook, setFirstLook] = useState(false);
  // "Now you can see what it's made of." (spec, Joy): the first holdings an account has, from an import.
  const saved = (r: Saved) => {
    setImporting(false);
    if (!r.first) return;
    setFirstLook(true);
    const el = held.current;
    if (el) void withCelebrate((c) => { c.burst({ over: el }); });
  };
  if (q.isPending) return <Skeleton lines={6} />;
  if (q.isError) return <Notice tone="error"><p>{q.error.message}</p></Notice>;
  const page = q.data;
  return (
    <div className="inv" data-testid="investment">
      {page.sends && <p className="inv-sends">{sendsLine(page.institution, page.sends)}</p>}
      <Figures year={page.year} />
      <GrowthChart points={page.series} since={page.since} />
      <div ref={held}>
        <Holdings page={page} onImport={canEdit ? () => setImporting(true) : undefined}
          cost={canEdit ? (r) => <CostAdd row={r} /> : undefined}
          fee={<AdvisoryFee accountId={account.id} advisory={page.advisory} canEdit={canEdit} />}
          cheer={firstLook ? <p className="inv-cheer">{FIRST_IMPORT_CHEER}</p> : undefined} />
      </div>
      {page.contributions && <ContributionsSection data={page.contributions} />}
      {importing && (
        <Suspense fallback={null}>
          <PositionsImport accountId={account.id} onClose={() => setImporting(false)} onSaved={saved} />
        </Suspense>
      )}
    </div>
  );
}
