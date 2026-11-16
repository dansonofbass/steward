import { ExternalLink, Plus } from 'lucide-react';
import { useRef, useState, type ReactNode } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { money } from '../../../lib/format';
import { Button } from '../../../ui/Button';
import { Notice } from '../../../ui/Notice';
import { Skeleton } from '../../../ui/Skeleton';
import { dollarsText, toHundredths } from '../../settings/money';
import { failure } from '../../settings/shared';
import { patchAccount, saveFact, setBalance, setWhere, useProfileHome, type Thing } from '../api';
import {
  ADD_PROPERTY, ADDED, HOME_NAME_DEFAULT, LABEL, MOVED_WHERE, REDFIN, REDFIN_NOTE, REDFIN_URL, REMOVE, REMOVE_NAMED, REMOVED, VALUE, VALUE_NEEDED, WHERE_NOTE, WHERE_YOU_LIVE,
} from '../copy';
import { ProfileField, invalidateProfile, useFieldMode } from '../field';
import { collapse } from '../motion';
import type { BodyProps } from '../sections';
import { NewThing } from './NewThing';
import { useOffer } from './offer';

const over0 = (needed: string) => (t: string) => { const p = toHundredths(t); return 'error' in p || p.value <= 0 ? needed : null; };
const positive = over0(VALUE_NEEDED);
const cents = (t: string) => (toHundredths(t) as { value: number }).value;

export function ThingRow({ thing, valueLabel, needed = VALUE_NEEDED, saveValue, onRemove, children }: {
  thing: Thing; valueLabel: string; needed?: string; saveValue: (c: number) => Promise<string | null>;
  onRemove: (t: Thing, row: HTMLElement | null) => void; children?: ReactNode;
}) {
  const row = useRef<HTMLDivElement>(null);
  const { canEdit } = useFieldMode();
  return (
    <div ref={row} className="home-row">
      {/* P32: a rename isn't undoable, so it answers with no token */}
      <ProfileField label={LABEL} input="text" maxLength={120} text={thing.name} shown={thing.name} check={(t) => (t.trim() ? null : LABEL)}
        save={async (t) => { await patchAccount(thing.account_id, { name: t.trim() }); return null; }} />
      <ProfileField label={valueLabel} input="money" text={thing.value_cents === null ? '' : dollarsText(thing.value_cents)}
        shown={thing.value_cents === null ? '' : money(thing.value_cents)} check={over0(needed)} save={(t) => saveValue(cents(t))} />
      {children}
      {canEdit && <Button variant="quiet" aria-label={REMOVE_NAMED.replace('{name}', thing.name)} onClick={() => onRemove(thing, row.current)}>{REMOVE}</Button>}
    </div>
  );
}

/** Removing a home or a car deactivates it (its balance history stays), folds the row away and offers Undo. */
export function useRemove() {
  const qc = useQueryClient();
  const [hidden, setHidden] = useState<number[]>([]);
  const { offer, view } = useOffer(() => setHidden([]));
  const [failed, setFailed] = useState<string | null>(null);
  const remove = (t: Thing, row: HTMLElement | null) => {
    collapse(row, () => setHidden((h) => [...h, t.account_id]));
    patchAccount(t.account_id, { is_active: false }).then(async (r) => {
      offer(REMOVED.replace('{name}', t.name), r.undo);
      await invalidateProfile(qc);
    }).catch((e) => { setHidden((h) => h.filter((x) => x !== t.account_id)); setFailed(failure(e)); });
  };
  return { hidden, remove, offer, view: <>{failed && <Notice tone="error">{failed}</Notice>}{view}</> };
}

export function Homes(_: BodyProps) {
  const home = useProfileHome();
  const qc = useQueryClient();
  const [adding, setAdding] = useState(false);
  const { canEdit } = useFieldMode();
  const { hidden, remove, offer, view } = useRemove();
  if (home.error) return <Notice tone="error">{home.error.message}</Notice>;
  if (!home.data) return <Skeleton lines={3} />;
  const h = home.data;
  const props = h.properties.filter((p) => !hidden.includes(p.account_id));
  const where = h.where_you_live;
  const saveFor = (id: number) => async (c: number) =>
    id === where || props.length === 1 ? saveFact('home.value_cents', String(c)) : (await setBalance(id, c)).undo;
  return (
    <div className="stack">
      {props.length === 0 && !adding && (   // the first home: its value makes the Home account (today's one home value)
        <ProfileField label={VALUE} input="money" text="" shown="" check={positive} save={(t) => saveFact('home.value_cents', String(cents(t)))} />
      )}
      {props.map((p) => (
        <ThingRow key={p.account_id} thing={p} valueLabel={VALUE} saveValue={saveFor(p.account_id)} onRemove={remove}>
          {props.length > 1 && !canEdit && p.account_id === where && <p className="small muted">{WHERE_YOU_LIVE}</p>}
          {props.length > 1 && canEdit && (
            <label className="radio-row">
              <input type="radio" name="where-you-live" checked={p.account_id === where}
                onChange={() => void setWhere(p.account_id).then((r) => { offer(MOVED_WHERE.replace('{name}', p.name), r.undo); return invalidateProfile(qc); })} />
              <span>{WHERE_YOU_LIVE}</span>
            </label>
          )}
        </ThingRow>
      ))}
      {props.length > 1 && <p className="small muted">{WHERE_NOTE}</p>}
      {adding && canEdit && <NewThing type="property" valueLabel={VALUE} placeholder={HOME_NAME_DEFAULT} onMade={(name, tokens) => { setAdding(false); offer(ADDED.replace('{name}', name), ...tokens); }} />}
      <a className="link" href={REDFIN_URL} target="_blank" rel="noopener noreferrer"><ExternalLink className="i" size={20} aria-hidden="true" />{REDFIN}</a>
      <p className="small muted">{REDFIN_NOTE}</p>
      {canEdit && <div className="ob-form-actions"><Button variant="quiet" icon={Plus} disabled={adding} onClick={() => setAdding(true)}>{ADD_PROPERTY}</Button></div>}
      {view}
    </div>
  );
}
