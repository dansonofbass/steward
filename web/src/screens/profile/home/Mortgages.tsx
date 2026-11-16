import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { chainTokens } from '../../../api/profile';
import { dateLabel, dollars, money } from '../../../lib/format';
import { Field } from '../../../ui/Field';
import { Notice } from '../../../ui/Notice';
import { Skeleton } from '../../../ui/Skeleton';
import { dollarsText, toHundredths } from '../../settings/money';
import { bpToRate, parseRate } from '../home';
import { patchAccount, saveFact, setBalance, useProfileHome, type HomeData, type Loan, type Thing } from '../api';
import {
  A_MONTH, ADD_MORTGAGE, ADDED, BALANCE_FROM, BALANCE_NEEDED, LOAN_BALANCE, MORTGAGE_CHANGED, MORTGAGE_NAME, NO_MORTGAGE, OTHER_PROPERTY, PAYMENT, PAYMENT_HINT, PAYMENT_NEEDED, PAYMENT_SOURCE, PAYMENT_VARIED, RATE, RATE_PLACEHOLDER,
} from '../copy';
import { ProfileField, ShownValue, invalidateProfile, useFieldMode } from '../field';
import type { BodyProps } from '../sections';
import { NewThing } from './NewThing';
import { useOffer, type Offer } from './offer';
import { Payoff } from './Payoff';

const ADD = '__add';

function rateText(m: Loan): string {
  return m.rate_bp === null ? '' : bpToRate(String(m.rate_bp));
}

/** One mortgage's figures. Where you live's carries the Plan's payment and payoff date (P19-P22). */
export function MortgageFields({ m, main, offer }: { m: Loan; main: boolean; offer: Offer }) {
  const qc = useQueryClient();
  const [rate, setRate] = useState(rateText(m));
  const prefill = main && !m.payment_cents && m.detected ? dollarsText(m.detected.amount_cents) : null;
  const [payment, setPayment] = useState(m.payment_cents ? dollarsText(m.payment_cents) : prefill ?? '');
  const [typedPayment, setTypedPayment] = useState(false);
  const owed = m.balance_cents;
  return (
    <div className="stack">
      {m.manual ? (
        <ProfileField label={LOAN_BALANCE} input="money" text={owed === null ? '' : dollarsText(owed)} shown={owed === null ? '' : money(owed)}
          check={(t) => { const p = toHundredths(t); return 'error' in p || p.value < 0 ? BALANCE_NEEDED : null; }}
          save={async (t) => (await setBalance(m.account_id, -(toHundredths(t) as { value: number }).value)).undo} />
      ) : (
        <p className="ob-balance">
          <span className="ob-balance__label">{LOAN_BALANCE}</span>
          <span className="ob-balance__value">{owed === null ? '' : money(owed)}</span>
          <span className="small muted">{BALANCE_FROM.replace('{bank}', m.institution).replace('{date}', m.as_of ? dateLabel(m.as_of, new Date()) : '')}</span>
        </p>
      )}
      <ProfileField label={RATE} input="percent" placeholder={RATE_PLACEHOLDER} text={rateText(m)} shown={m.rate_bp === null ? '' : `${rateText(m)}%`}
        onText={setRate} check={(t) => { const r = parseRate(t); return 'error' in r ? r.error : null; }}
        save={async (t) => {
          const r = parseRate(t) as { bp: string };
          const reply = await patchAccount(m.account_id, { rate_bp: Math.round(Number(r.bp)) });
          // where you live also keeps the fact, for history; one Undo reverts both (else the fact stands in for a null account rate)
          const fact = main ? await saveFact('mortgage.rate_bp', r.bp) : null;
          await qc.invalidateQueries({ queryKey: ['profile-home'] });
          return chainTokens(reply.undo, fact);
        }} />
      {main && (
        <>
          <ProfileField label={PAYMENT} input="money" post={A_MONTH} hint={PAYMENT_HINT} text={payment} unsaved={prefill !== null}
            shown={m.payment_cents ? `${dollars(m.payment_cents)} ${A_MONTH}` : ''}
            onText={(t) => { setPayment(t); setTypedPayment(true); }}
            check={(t) => { const p = toHundredths(t); return 'error' in p || p.value <= 0 ? PAYMENT_NEEDED : null; }}
            save={(t) => saveFact('mortgage.payment_cents', String((toHundredths(t) as { value: number }).value))} />
          {m.detected && !typedPayment && !m.payment_cents && (
            <p className="small muted">
              {PAYMENT_SOURCE.replace('{date}', dateLabel(m.detected.posted_at, new Date())).replace('{mortgage}', m.name)}
              {m.detected.varied && ` ${PAYMENT_VARIED.replace('{lo}', dollars(m.detected.varied.lo)).replace('{hi}', dollars(m.detected.varied.hi))}`}
            </p>
          )}
          <Payoff owedCents={owed} rate={rate} payment={payment} saved={m.payoff_date ?? null} offer={offer} />
        </>
      )}
      {!main && <p className="small muted">{OTHER_PROPERTY}</p>}
    </div>
  );
}

function Block({ p, h, main, offer }: { p: Thing & { mortgage: Loan | null }; h: HomeData; main: boolean; offer: Offer }) {
  const qc = useQueryClient();
  const { canEdit } = useFieldMode();
  const [adding, setAdding] = useState(false);
  const choose = async (value: string) => {
    if (value === ADD) { setAdding(true); return; }
    const r = await patchAccount(p.account_id, { loan_id: value === '' ? null : Number(value) });
    offer(MORTGAGE_CHANGED.replace('{name}', p.name), r.undo);
    await invalidateProfile(qc);
  };
  return (
    <section className="card prof-card__step" aria-labelledby={`mortgage-${p.account_id}-h`}>
      <h3 id={`mortgage-${p.account_id}-h`}>{p.name}</h3>
      {!canEdit ? <ShownValue label={MORTGAGE_NAME} text={p.mortgage?.name ?? NO_MORTGAGE} /> : <Field label={MORTGAGE_NAME}>
        <select value={adding ? ADD : p.mortgage ? String(p.mortgage.account_id) : ''} onChange={(e) => void choose(e.target.value)}>
          <option value="">{NO_MORTGAGE}</option>
          {p.mortgage && <option value={String(p.mortgage.account_id)}>{p.mortgage.name}</option>}
          {h.mortgages.map((m) => <option key={m.account_id} value={String(m.account_id)}>{m.name}</option>)}
          <option value={ADD}>{ADD_MORTGAGE}</option>
        </select>
      </Field>}
      {adding && canEdit &&<NewThing type="mortgage" name={MORTGAGE_NAME} valueLabel={LOAN_BALANCE} owed linkTo={p.account_id}
        onMade={(name, undo) => { setAdding(false); offer(ADDED.replace('{name}', name), ...undo); }} />}
      {p.mortgage && !adding && <MortgageFields m={p.mortgage} main={main} offer={offer} />}
    </section>
  );
}

export function Mortgages(_: BodyProps) {
  const home = useProfileHome();
  const { offer, view } = useOffer();
  if (home.error) return <Notice tone="error">{home.error.message}</Notice>;
  if (!home.data) return <Skeleton lines={4} />;
  const h = home.data;
  return (
    <div className="stack">
      {h.properties.map((p) => <Block key={p.account_id} p={p} h={h} main={p.account_id === h.where_you_live} offer={offer} />)}
      {view}
    </div>
  );
}
