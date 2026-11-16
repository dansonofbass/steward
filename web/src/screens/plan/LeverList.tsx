import { useEffect, useState } from 'react';
import { Tip } from '../../ui/Tip';
import type { LeverField, LeverKey, LeverSpec, LeverState, LeverValue } from './api';
import { LEVERS_INTRO, LEVERS_TIP, WHAT_WOULD_CHANGE_IT } from './copy';
import { LeverRow } from './LeverRow';
import { impactFor, isPinned, rankedKeys, type RowCtx } from './levers';
import type { PlanLive } from './usePlanDraft';

/** Design decision 3: every row starts closed. */
export const DEFAULT_OPEN: LeverKey[] = [];

type Props = {
  specs: LeverSpec[]; server: LeverState; live: PlanLive; ctx: RowCtx; epoch: number;
  onAssumed: (f: LeverField, v: LeverValue) => void; onTry: (f: LeverField, v: LeverValue) => void;
  onTryThis: (k: LeverKey) => void; onUnpin: (k: LeverKey) => void;
};

export function LeverList({ specs, server, live, ctx, epoch, onAssumed, onTry, onTryThis, onUnpin }: Props) {
  const [open, setOpen] = useState<Set<LeverKey>>(() => new Set(DEFAULT_OPEN));
  // The ranking is frozen once known, so rows never jump under a finger; it re-ranks after a save or "Reset".
  const [order, setOrder] = useState<LeverKey[] | null>(null);
  useEffect(() => { setOrder(null); }, [epoch]);
  useEffect(() => {
    if (order === null && live.impacts && !live.impactsPending) setOrder(rankedKeys(live.impacts));
  }, [order, live.impacts, live.impactsPending]);

  const keys = order ?? specs.map((s) => s.key);
  const toggle = (k: LeverKey) => setOpen((s) => { const n = new Set(s); if (n.has(k)) n.delete(k); else n.add(k); return n; });
  const college = (live.impacts ?? []).filter((i) => i.key === 'college');
  return (
    <section className="sec" aria-labelledby="lev-h">
      <h2 id="lev-h">{WHAT_WOULD_CHANGE_IT} <Tip>{LEVERS_TIP}</Tip></h2>
      <p className="sec__intro">{LEVERS_INTRO}</p>
      <div className="card levers">
        {keys.map((k) => {
          const spec = specs.find((s) => s.key === k);
          if (!spec) return null;
          return (
            <LeverRow key={k} spec={spec} impact={impactFor(live.impacts, k)} childImpacts={college} impactsPending={live.impactsPending}
              assumed={live.shown.assumed} trial={live.shown.try} saved={server.assumed}
              changed={live.changed.includes(k)} pinned={isPinned(server, live.draft, k)} note={live.notes[k]}
              open={open.has(k)} onToggle={() => toggle(k)} onAssumed={onAssumed} onTry={onTry}
              onTryThis={() => onTryThis(k)} onUnpin={() => onUnpin(k)} ctx={ctx} />
          );
        })}
      </div>
    </section>
  );
}
