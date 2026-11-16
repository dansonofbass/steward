import { useQueryClient } from '@tanstack/react-query';
import { Briefcase, User } from 'lucide-react';
import { useState } from 'react';
import { api, json } from '../../api/client';
import type { Txn } from '../../api/types';
import { BUSINESS, BUSINESS_OR_PERSONAL_Q, LOOKS_LIKE_BUSINESS, PERSONAL } from '../../lib/copy';
import { dateLabel } from '../../lib/format';
import { Button } from '../../ui/Button';
import { Money } from '../../ui/Money';
import { Notice } from '../../ui/Notice';

type Props = { rows: Txn[]; today: Date };

/** Business plan Task 11: money out the categorizer thinks is likely business. One tap answers it for good. */
export function BusinessQuestions({ rows, today }: Props) {
  const qc = useQueryClient();
  const [gone, setGone] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const shown = rows.filter((t) => !gone.has(t.id));
  if (shown.length === 0) return null;

  async function answer(t: Txn, a: 'business' | 'personal') {
    setBusy(t.id);
    setError(null);
    try {
      await api<Txn>(`/api/business/suggestions/${t.id}`, json({ answer: a }));
      setGone((s) => new Set(s).add(t.id));
      for (const key of ['review', 'business', 'spending', 'plan']) void qc.invalidateQueries({ queryKey: [key] });
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Something went wrong.');
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="bq stack" aria-labelledby="bq-title">
      <h2 id="bq-title">{BUSINESS_OR_PERSONAL_Q}</h2>
      <p className="muted">{LOOKS_LIKE_BUSINESS}</p>
      {error && <Notice tone="error">{error}</Notice>}
      <ul className="bq__list">
        {shown.map((t) => {
          const name = t.merchant || t.raw_description;
          return (
            <li key={t.id} className="card bq__row">
              <div className="bq__what">
                <span className="bq__name">{name}</span>
                <span className="small muted">{dateLabel(t.posted_at, today)} · {t.account_name}</span>
              </div>
              <Money cents={t.amount_cents} />
              <div className="bq__actions">
                <Button variant="quiet" icon={Briefcase} busy={busy === t.id} aria-label={`${BUSINESS}: ${name}`} onClick={() => void answer(t, 'business')}>{BUSINESS}</Button>
                <Button variant="quiet" icon={User} disabled={busy === t.id} aria-label={`${PERSONAL}: ${name}`} onClick={() => void answer(t, 'personal')}>{PERSONAL}</Button>
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
