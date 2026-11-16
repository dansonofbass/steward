import { useState } from 'react';
import { FOLDS } from './copy';

export type FoldKey = keyof typeof FOLDS;
export const FOLD_KEYS: FoldKey[] = ['markets', 'taxes', 'ss', 'lifespans', 'costs'];
const STORE = 'steward-how-folds';

/** Which folds this viewer left open: a per-viewer convenience, so a private window or a blocked store just starts
 *  them closed. */
function readOpen(): Set<string> {
  try {
    const v: unknown = JSON.parse(localStorage.getItem(STORE) ?? '[]');
    return new Set(Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : []);
  } catch {
    return new Set();
  }
}
function writeOpen(open: Set<string>) {
  try { localStorage.setItem(STORE, JSON.stringify([...open])); } catch { /* nothing to keep it in: closed next time */ }
}

/** Every other assumption, in five quiet rows that open to today's exact lines, sources and all (P28). */
export function Folds({ folds }: { folds: Record<FoldKey, string[]> }) {
  const [open, setOpen] = useState(readOpen);
  function toggle(k: FoldKey, isOpen: boolean) {
    if (open.has(k) === isOpen) return;
    const next = new Set(open);
    if (isOpen) next.add(k); else next.delete(k);
    setOpen(next);
    writeOpen(next);
  }
  return (
    <div className="how-folds">
      {FOLD_KEYS.filter((k) => folds[k].length > 0).map((k) => (
        <details key={k} className="how-fold" open={open.has(k)} onToggle={(e) => toggle(k, e.currentTarget.open)}>
          <summary>{FOLDS[k]}</summary>
          <ul className="how-list">{folds[k].map((s) => <li key={s}>{s}</li>)}</ul>
        </details>
      ))}
    </div>
  );
}
