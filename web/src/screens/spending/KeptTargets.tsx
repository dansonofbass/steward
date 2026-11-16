import { useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { undoToken } from '../../api/profile';
import { checkAgain } from '../../api/spending';
import type { KeptTarget } from '../../api/types';
import { label } from '../../lib/categories';
import { collapse } from '../../lib/collapse';
import { dollars } from '../../lib/format';
import { Button } from '../../ui/Button';
import { Notice } from '../../ui/Notice';
import { UndoToast } from '../../ui/UndoToast';
import { monthShort } from '../cashflow/months';
import { failure } from '../settings/shared';
import * as C from './copy';
import { fill } from './format';

/** Kept targets (P20), at the foot of Set targets: each target someone kept, until when, with Check again. */
export function KeptTargets({ kept, canEdit }: { kept: KeptTarget[]; canEdit: boolean }) {
  const qc = useQueryClient();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<{ text: string; token: string } | null>(null);
  async function again(k: KeptTarget, row: HTMLElement | null) {
    setBusy(k.category);
    setError(null);
    try {
      const r = await checkAgain(k.category);
      collapse(row, () => {
        setToast({ text: fill(C.CHECK_AGAIN_TOAST, { name: label(k.category) }), token: r.undo });
        void qc.invalidateQueries({ queryKey: ['spending'] });
      });
    } catch (e) {
      setError(failure(e));
    } finally {
      setBusy(null);
    }
  }
  async function undo() {
    const t = toast?.token;
    setToast(null);
    try { if (t) await undoToken(t); } catch (e) { setError(failure(e)); }
    await qc.invalidateQueries({ queryKey: ['spending'] });
  }
  return (
    <>
      {kept.length > 0 && (
        <details className="sp-kept">
          <summary>{C.KEPT_FOLD}</summary>
          <ul className="sp-kept__rows">
            {kept.map((k) => (
              <li key={k.category} className="sp-kept__row" data-testid="kept-row">
                <span>{fill(C.KEPT_ROW, { name: label(k.category), target: dollars(k.target_cents), month: monthShort(k.until.slice(0, 7)) })}</span>
                {canEdit && <Button variant="quiet" busy={busy === k.category} disabled={busy !== null}
                  onClick={(e) => void again(k, e.currentTarget.closest('li'))}>{C.CHECK_AGAIN}</Button>}
              </li>
            ))}
          </ul>
        </details>
      )}
      {error && <Notice tone="error">{error}</Notice>}
      {toast && <UndoToast text={toast.text} onUndo={() => void undo()} onClose={() => setToast(null)} />}
    </>
  );
}
