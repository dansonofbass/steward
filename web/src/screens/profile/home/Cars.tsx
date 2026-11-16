import { ExternalLink, Plus } from 'lucide-react';
import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Button } from '../../../ui/Button';
import { Field } from '../../../ui/Field';
import { Notice } from '../../../ui/Notice';
import { Skeleton } from '../../../ui/Skeleton';
import { patchAccount, setBalance, useProfileHome, type Loan, type Thing } from '../api';
import { ADDED, ADD_CAR, ADD_LOAN, ANY_CARS, CAR_PLACEHOLDER, KBB, KBB_NOTE, KBB_URL, LOAN_BALANCE, LOAN_CHANGED, LOAN_NAME, NO, NO_LOAN, VALUE_CAR, VALUE_CAR_NEEDED, YES } from '../copy';
import { ShownValue, invalidateProfile, useFieldMode } from '../field';
import type { BodyProps } from '../sections';
import { ThingRow, useRemove } from './Homes';
import { NewThing } from './NewThing';
import type { Offer } from './offer';

const ADD = '__add';

function LoanPick({ car, loans, offer }: { car: Thing & { loan: Loan | null }; loans: Loan[]; offer: Offer }) {
  const qc = useQueryClient();
  const { canEdit } = useFieldMode();
  const [adding, setAdding] = useState(false);
  if (!canEdit) return <ShownValue label={LOAN_NAME} text={car.loan?.name ?? NO_LOAN} />;
  return (
    <>
      <Field label={LOAN_NAME}>
        <select value={adding ? ADD : car.loan ? String(car.loan.account_id) : ''} onChange={(e) => {
          if (e.target.value === ADD) { setAdding(true); return; }
          void patchAccount(car.account_id, { loan_id: e.target.value === '' ? null : Number(e.target.value) }).then((r) => {
            offer(LOAN_CHANGED.replace('{name}', car.name), r.undo);
            return invalidateProfile(qc);
          });
        }}>
          <option value="">{NO_LOAN}</option>
          {car.loan && <option value={String(car.loan.account_id)}>{car.loan.name}</option>}
          {loans.map((l) => <option key={l.account_id} value={String(l.account_id)}>{l.name}</option>)}
          <option value={ADD}>{ADD_LOAN}</option>
        </select>
      </Field>
      {adding && <NewThing type="loan" name={LOAN_NAME} valueLabel={LOAN_BALANCE} owed linkTo={car.account_id} onMade={(name, undo) => { setAdding(false); offer(ADDED.replace('{name}', name), ...undo); }} />}
    </>
  );
}

export function Cars(_: BodyProps) {
  const home = useProfileHome();
  const [any, setAny] = useState<boolean | null>(null);
  const [adding, setAdding] = useState(false);
  const { canEdit } = useFieldMode();
  const { hidden, remove, offer, view } = useRemove();
  if (home.error) return <Notice tone="error">{home.error.message}</Notice>;
  if (!home.data) return <Skeleton lines={3} />;
  const h = home.data;
  const cars = h.cars.filter((c) => !hidden.includes(c.account_id));
  const yes = any ?? cars.length > 0;
  return (
    <div className="stack">
      {!canEdit ? <ShownValue label={ANY_CARS} text={yes ? YES : NO} /> : <fieldset className="field plain-fieldset">
        <legend className="field__label">{ANY_CARS}</legend>
        <div className="ob-radios">
          {([[true, YES], [false, NO]] as const).map(([v, text]) => (
            <label key={text} className="radio-row">
              <input type="radio" name="any-cars" checked={yes === v} onChange={() => setAny(v)} /><span>{text}</span>
            </label>
          ))}
        </div>
      </fieldset>}
      {yes && (
        <>
          {cars.map((c) => (
            <ThingRow key={c.account_id} thing={c} valueLabel={VALUE_CAR} needed={VALUE_CAR_NEEDED} onRemove={remove}
              saveValue={async (cents) => (await setBalance(c.account_id, cents)).undo}>
              <LoanPick car={c} loans={h.loans} offer={offer} />
            </ThingRow>
          ))}
          {canEdit && (adding || cars.length === 0) && <NewThing type="vehicle" valueLabel={VALUE_CAR} needed={VALUE_CAR_NEEDED} placeholder={CAR_PLACEHOLDER}
            onMade={(name, undo) => { setAdding(false); offer(ADDED.replace('{name}', name), ...undo); }} />}
          <a className="link" href={KBB_URL} target="_blank" rel="noopener noreferrer"><ExternalLink className="i" size={20} aria-hidden="true" />{KBB}</a>
          <p className="small muted">{KBB_NOTE}</p>
          {canEdit && <div className="ob-form-actions"><Button variant="quiet" icon={Plus} disabled={adding} onClick={() => setAdding(true)}>{ADD_CAR}</Button></div>}
        </>
      )}
      {view}
    </div>
  );
}
