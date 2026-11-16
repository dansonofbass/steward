import { useEffect, useState } from 'react';
import { useChildren, type Child, type KidsList } from '../../../api/household';
import { Button } from '../../../ui/Button';
import { Field } from '../../../ui/Field';
import { MoneyInput } from '../../../ui/MoneyInput';
import { Notice } from '../../../ui/Notice';
import { Skeleton } from '../../../ui/Skeleton';
import { dollarsText, toHundredths } from '../../settings/money';
import { typeLabel } from '../../settings/shared';
import { A_MONTH, LINK_AND_TYPE, LINK_IT, MONTHLY, MONTHLY_SOURCE, NO_529, SUGGEST, SUGGEST_OTHER, THEIR_529, UNLINKED } from '../copy';
import type { BodyProps } from '../sections';
import { choiceOf, useLine } from './Cover';
import { useKidSave } from './kidSave';
import { SavedUndo } from './SavedUndo';

export function KidPlan({ kid, data }: { kid: Child; data: KidsList }) {
  const { save, error, undo, undoIt, busy } = useKidSave(kid.id);
  const [account, setAccount] = useState<number | null>(kid.account_id);
  const [monthly, setMonthly] = useState(dollarsText(kid.monthly_contribution_cents));
  const [prefilled, setPrefilled] = useState(false);
  useEffect(() => {      // the server's values win after an Undo (or any refetch) unless a change is still on its way
    if (busy()) return;
    setAccount(kid.account_id);
    setMonthly(dollarsText(kid.monthly_contribution_cents));
    setPrefilled(false);
  }, [kid.account_id, kid.monthly_contribution_cents]); // eslint-disable-line react-hooks/exhaustive-deps
  const taken = new Set(data.children.filter((k) => k.id !== kid.id).map((k) => k.account_id));
  const free = data.plans.filter((p) => !taken.has(p.account_id));
  const plan = data.plans.find((p) => p.account_id === account) ?? null;
  const hint = data.suggestions.find((s) => s.child_id === kid.id);
  const typed = toHundredths(monthly);
  const cents = 'error' in typed ? kid.monthly_contribution_cents : typed.value;
  const line = useLine(choiceOf(kid, { balance_cents: plan?.balance_cents ?? 0, real_return: plan?.real_return ?? 0, monthly_cents: cents }),
    kid.label, account !== null, data.college);

  function link(id: number | null, setType = false) {
    setAccount(id);
    const p = data.plans.find((x) => x.account_id === id);
    const body: Record<string, unknown> = { account_id: id, ...(setType ? { set_type: true } : {}) };
    if (p?.deposits_monthly_cents && kid.monthly_contribution_cents === 0) {   // P17: prefilled from the deposits
      body.monthly_contribution_cents = p.deposits_monthly_cents;
      setMonthly(dollarsText(p.deposits_monthly_cents));
      setPrefilled(true);
    }
    save(body);
  }
  return (
    <section className="card prof-card__step" aria-label={kid.label}>
      <h3>{kid.label}</h3>
      {account === null && hint && (
        <div className="kid-suggest">
          <p>{(hint.account_type === 'plan529' ? SUGGEST : SUGGEST_OTHER).replace('{account}', hint.account_name).replace('{name}', kid.label)
            .replace('{type}', typeLabel(hint.account_type as never))}</p>
          <Button variant="quiet" onClick={() => link(hint.account_id, hint.account_type !== 'plan529')}>
            {hint.account_type === 'plan529' ? LINK_IT : LINK_AND_TYPE}
          </Button>
        </div>
      )}
      <Field label={THEIR_529}>
        <select value={account === null ? '' : String(account)} onChange={(e) => link(e.target.value === '' ? null : Number(e.target.value))}>
          <option value="">{NO_529}</option>
          {free.map((p) => <option key={p.account_id} value={String(p.account_id)}>{p.name}</option>)}
          {hint && account === hint.account_id && !free.some((p) => p.account_id === hint.account_id) && (
            <option value={String(hint.account_id)}>{hint.account_name}</option>
          )}
        </select>
      </Field>
      <SavedUndo show={!!undo} onUndo={() => void undoIt()} />
      <Field label={MONTHLY} hint={prefilled ? MONTHLY_SOURCE : undefined} error={error ?? undefined}>
        <MoneyInput post={A_MONTH} value={monthly} onValueChange={(v) => {
          setMonthly(v);
          setPrefilled(false);
          const p = toHundredths(v);
          if (!('error' in p) && p.value >= 0) save({ monthly_contribution_cents: p.value }, 600);
        }} />
      </Field>
      <p className="kid-line" aria-live="polite">{line}</p>
    </section>
  );
}

export function Plans(_: BodyProps) {
  const kids = useChildren();
  if (kids.error) return <Notice tone="error">{kids.error.message}</Notice>;
  if (!kids.data) return <Skeleton lines={4} />;
  const linked = new Set(kids.data.children.map((k) => k.account_id));
  return (
    <div className="stack">
      {kids.data.plans.filter((p) => !linked.has(p.account_id)).map((p) => (
        <Notice key={p.account_id} tone="warn">{UNLINKED.replace('{account}', p.name)}</Notice>
      ))}
      {kids.data.children.map((k) => <KidPlan key={k.id} kid={k} data={kids.data!} />)}
    </div>
  );
}
