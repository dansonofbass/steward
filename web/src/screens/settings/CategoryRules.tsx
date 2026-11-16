import { useQueryClient } from '@tanstack/react-query';
import { Trash2 } from 'lucide-react';
import { useState } from 'react';
import { api, del, patch } from '../../api/client';
import { useCategoryRules } from '../../api/hooks';
import type { CategoryRule } from '../../api/types';
import {
  N_TRANSACTIONS, ONE_TRANSACTION, REMOVE, REMOVE_RULE_BODY, REMOVE_RULE_FOR, REMOVE_RULE_TITLE, RULE_HAS_NOTE, RULE_REMOVED, RULE_NAMES_ONLY, RULES_EMPTY,
  RULES_INTRO, S_CATEGORY_RULES,
} from '../../lib/copy';
import { money } from '../../lib/format';
import { useRemoval } from '../../lib/useRemoval';
import { Button } from '../../ui/Button';
import { Card } from '../../ui/Card';
import { CategoryField } from '../../ui/CategoryMenu';
import { ConfirmSheet } from '../../ui/ConfirmSheet';
import { EmptyState } from '../../ui/EmptyState';
import { Notice } from '../../ui/Notice';
import { RemovalLine } from '../../ui/RemovalLine';
import { Skeleton } from '../../ui/Skeleton';

/** "PAYPAL · $13.99 · Disney+ · has a note": the pattern, its amount and its name; never the note itself (P36). */
export function ruleLine(r: CategoryRule): string {
  return [r.pattern, r.amount_cents !== null ? money(Math.abs(r.amount_cents)) : null, r.nickname, r.has_note ? RULE_HAS_NOTE : null]
    .filter((x): x is string => !!x).join(' · ');
}

const ruleName = (r: CategoryRule) => r.merchant ?? r.pattern;

/** Settings → Money sources → Category rules (decision 2, ruling 17): the household's own rules, most rows first.
 *  A change or a removal touches no past transaction; the API says so and the intro repeats it. A removal has no
 *  Undo, so it asks first (T3). */
export default function CategoryRules() {
  const q = useCategoryRules();
  const qc = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [doomed, setDoomed] = useState<CategoryRule | null>(null);
  // One write at a time: a second click while one is in flight would send a second request.
  const [busy, setBusy] = useState(false);
  const removal = useRemoval();

  async function run(action: () => Promise<unknown>, done?: () => void) {
    if (busy) return;
    setBusy(true);
    setError(null);
    removal.clear();
    try {
      await action();
      await qc.invalidateQueries({ queryKey: ['category-rules'] });
      done?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong.');
    } finally {
      setBusy(false);
    }
  }
  const change = (r: CategoryRule, category: string) => {
    if (category !== r.category) void run(() => api<CategoryRule>(`/api/categorize/rules/${r.id}`, patch({ category })));
  };
  const remove = (r: CategoryRule) => {
    void run(() => api<void>(`/api/categorize/rules/${r.id}`, del()), () => { removal.removed(RULE_REMOVED.replace('{name}', ruleName(r))); setDoomed(null); });
  };

  return (
    <section className="stack" aria-labelledby="rules-h">
      <h2 id="rules-h" ref={removal.anchor} tabIndex={-1}>{S_CATEGORY_RULES}</h2>
      <p className="muted">{RULES_INTRO}</p>
      <RemovalLine removal={removal} />
      {error && !doomed && <Notice tone="error">{error}</Notice>}
      {q.isError ? <Notice tone="error">{q.error.message}</Notice>
        : !q.data ? <Card><Skeleton lines={3} /></Card>
        : q.data.rules.length === 0 ? <Card><EmptyState title={RULES_EMPTY} /></Card> : (
          <ul className="card lines rules">
            {q.data.rules.map((r) => (
              <li key={r.id} className="line rule">
                <span className="rule__desc">
                  {r.merchant ? <><strong>{r.merchant}</strong><span className="raw">{ruleLine(r)}</span></> : <strong>{ruleLine(r)}</strong>}
                </span>
                {r.category === null ? <span className="rule__names muted">{RULE_NAMES_ONLY}</span> : <CategoryField value={r.category} onChange={(k) => change(r, k)} withUnsorted={false} disabled={busy} />}
                <span className="rule__rows muted">{r.rows === 1 ? ONE_TRANSACTION : N_TRANSACTIONS.replace('{n}', String(r.rows))}</span>
                <Button variant="quiet" disabled={busy} aria-label={REMOVE_RULE_FOR.replace('{name}', ruleName(r))} onClick={() => { setError(null); setDoomed(r); }}>{REMOVE}</Button>
              </li>
            ))}
          </ul>
        )}
      <ConfirmSheet open={doomed !== null} onClose={() => setDoomed(null)} title={doomed ? REMOVE_RULE_TITLE.replace('{name}', ruleName(doomed)) : ''}
        body={REMOVE_RULE_BODY} action={REMOVE} icon={Trash2} busy={busy} error={error} onConfirm={() => doomed && remove(doomed)}
        returnTo={removal.returnTo} />
    </section>
  );
}
