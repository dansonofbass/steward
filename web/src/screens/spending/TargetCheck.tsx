import { useQueryClient } from '@tanstack/react-query';
import { useRef, useState } from 'react';
import { answerCheck } from '../../api/spending';
import type { TargetCheck as Check } from '../../api/types';
import { label } from '../../lib/categories';
import { collapse } from '../../lib/collapse';
import { dollars } from '../../lib/format';
import { Button } from '../../ui/Button';
import { Notice } from '../../ui/Notice';
import { monthShort } from '../cashflow/months';
import { failure } from '../settings/shared';
import * as C from './copy';
import { fill } from './format';

export type Answered = { text: string; token: string };

/** The monthly target check (P19), atop Spending's current month, one at a time. Set writes the typical month; Keep
 *  leaves the target for three months. Either way the card folds away (instant under reduced motion) and the page's
 *  toast says what happened, with Undo. */
export function TargetCheck({ check, onAnswered }: { check: Check; onAnswered: (a: Answered) => void }) {
  const qc = useQueryClient();
  const card = useRef<HTMLElement>(null);
  const [busy, setBusy] = useState<'set' | 'keep' | null>(null);
  const [gone, setGone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const name = label(check.category);
  async function answer(a: 'set' | 'keep') {
    setBusy(a);
    setError(null);
    try {
      const r = await answerCheck(check.category, a, check.target_cents);
      const text = a === 'set'
        ? fill(C.SET_TOAST, { name, amount: dollars(r.target_cents) })
        : fill(C.KEEP_TOAST, { target: dollars(check.target_cents), month: monthShort((r.until ?? '').slice(0, 7)) });
      collapse(card.current, () => {
        setGone(true);
        onAnswered({ text, token: r.undo });
        void qc.invalidateQueries({ queryKey: ['spending'] });
      });
    } catch (e) {
      setError(failure(e));
      setBusy(null);
    }
  }
  if (gone) return null;
  return (
    <section ref={card} className="card sp-check" aria-label={fill(C.CHECK_LINE, { name })} data-testid="target-check">
      <p className="sp-check__line">
        <strong>{fill(C.CHECK_LINE, { name })}</strong>
        <span className="muted">{` · ${fill(C.CHECK_FIGURES, { target: dollars(check.target_cents), typical: dollars(check.typical_cents) })}`}</span>
      </p>
      <div className="row-actions">
        <Button busy={busy === 'set'} disabled={busy !== null} onClick={() => void answer('set')}>{fill(C.SET_TO, { typical: dollars(check.typical_cents) })}</Button>
        <Button variant="quiet" busy={busy === 'keep'} disabled={busy !== null} onClick={() => void answer('keep')}>{fill(C.KEEP, { target: dollars(check.target_cents) })}</Button>
      </div>
      {error && <Notice tone="error">{error}</Notice>}
    </section>
  );
}
