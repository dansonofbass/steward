import { useQueryClient } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useAccounts, useSetAsides } from '../../../api/hooks';
import { addSetAside, invalidateSetAsides } from '../../../api/setasides';
import type { SetAsideBody, SetAsideKind } from '../../../api/types';
import { useCanEdit } from '../../../book/BookContext';
import { Navigate, useNavigate } from '../../../book/links';
import { Skeleton } from '../../../ui/Skeleton';
import { dollarsText } from '../../settings/money';
import { BackLink } from '../parts';
import * as C from './copy';
import { emptyDraft, type Draft } from './model';
import { SetAsideForm } from './SetAsideForm';
import '../spending.css';
import './setasides.css';

/** The form's own cap on an amount (readDraft), in cents. */
const MAX_CENTS = 100_000_000;
const KINDS:SetAsideKind[] = ['yearly', 'twice_yearly', 'one_off'];

/** "Change first" puts the suggestion in the address (the amount in cents); anything missing keeps the empty draft's value. */
export function draftFromParams(sp: URLSearchParams, asOf: string): Draft {
  const d = emptyDraft(asOf);
  const kind = sp.get('kind');
  const amount = sp.get('amount');
  const num = (key: string, max: number, fallback: string) => {
    const v = sp.get(key);
    return v && /^\d{1,2}$/.test(v) && Number(v) >= 1 && Number(v) <= max ? String(Number(v)) : fallback;
  };
  return {
    ...d, name: (sp.get('name') ?? d.name).slice(0, 120), kind: kind && (KINDS as string[]).includes(kind) ? (kind as SetAsideKind) : d.kind,
    amount: amount && /^\d{1,12}$/.test(amount) && Number(amount) >= 1 && Number(amount) <= MAX_CENTS ? dollarsText(Number(amount)) : d.amount,
    dueMonth: num('due_month', 12, d.dueMonth), dueDay: num('due_day', 31, d.dueDay), secondMonth: num('second_month', 12, ''), secondDay: num('second_day', 31, ''),
    payeeKey: sp.get('payee_key') || null, payeeName: null, category: sp.get('category') || null,
  };
}

export function AddSetAside() {
  const [sp] = useSearchParams();
  const list = useSetAsides();
  const accounts = useAccounts();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const canEdit = useCanEdit();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const asOf = list.data?.as_of;
  // The form keeps its own copy of the draft; a refetch of the list must not hand it a new one.
  const initial = useMemo(() => (asOf ? draftFromParams(sp, asOf) : null), [sp, asOf]);
  const back = <BackLink to="/spending/setasides">{C.SETTING_ASIDE}</BackLink>;
  if (!canEdit) return <Navigate to="/spending/setasides" replace />;
  if (!list.data || !initial || !asOf) return <div className="screen spending" aria-busy="true">{back}<h1>{C.ADD}</h1><Skeleton lines={8} /></div>;
  const rows = list.data.rows;
  const sharedWith = (accountId: number) => rows.filter((r) => r.account?.id === accountId).map((r) => r.name);

  async function submit(body: SetAsideBody) {
    setBusy(true); setError(null);
    try {
      const made = await addSetAside(body);
      await invalidateSetAsides(qc);
      navigate(`/spending/setasides/${made.id}`, { replace: true, state: list.data?.first_visit ? { first: true } : null });
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }

  return (
    <div className="screen spending">
      {back}
      <header className="sp-head">
        <h1>{C.ADD}</h1>
        <p className="muted">{C.ADD_INTRO}</p>
      </header>
      <div className="card form-card">
        <SetAsideForm initial={initial} asOf={asOf} accounts={accounts.data?.accounts ?? []} busy={busy} error={error} submitLabel={C.SET_IT_ASIDE}
          onSubmit={(b) => void submit(b)} onCancel={() => navigate('/spending/setasides')} sharedWith={sharedWith} />
      </div>
    </div>
  );
}

export default AddSetAside;
