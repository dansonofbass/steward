import { useEffect, useState } from 'react';
import { useChildren, type Child, type CostLevel, type KidsList } from '../../../api/household';
import { Notice } from '../../../ui/Notice';
import { Skeleton } from '../../../ui/Skeleton';
import { COLLEGE_FROM, LIVING, LIVING_IN, LIVING_OUT, NOT_SURE_NOTE, PAST_AGE, SCHOOL, SCHOOLS, SCHOOL_ORDER, YOUR_SHARE } from '../copy';
import { outlook } from '../outlook';
import type { BodyProps } from '../sections';
import { consequence, type Choice } from './consequence';
import { useKidSave } from './kidSave';
import { SavedUndo } from './SavedUndo';

const planYear = () => new Date().getFullYear();

export function choiceOf(k: Child, over: Partial<Choice> = {}): Choice {
  return { birth_year: k.birth_year, level: k.cost_level, share_pct: k.share_pct, covers_living: k.covers_living,
    balance_cents: k.plan529?.balance_cents ?? 0, monthly_cents: k.monthly_contribution_cents,
    real_return: k.plan529?.real_return ?? 0, ...over };
}

/** The line, 150 ms after the last change (spec, The consequence line). */
export function useLine(c: Choice, name: string, linked: boolean, table: KidsList['college']): string {
  const [line, setLine] = useState(() => consequence(c, name, linked, table, planYear()));
  const key = JSON.stringify([c, name, linked]);
  useEffect(() => {
    const t = window.setTimeout(() => setLine(consequence(c, name, linked, table, planYear())), 150);
    return () => window.clearTimeout(t);
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps
  return line;
}

export function KidCover({ kid, table }: { kid: Child; table: KidsList['college'] }) {
  const { save, error, undo, undoIt, busy } = useKidSave(kid.id);
  const [level, setLevel] = useState<CostLevel>(kid.cost_level);
  const [share, setShare] = useState(kid.share_pct);
  const [living, setLiving] = useState(kid.covers_living);
  useEffect(() => {      // the server's values win after an Undo (or any refetch) unless a change is still on its way
    if (busy()) return;
    setLevel(kid.cost_level);
    setShare(kid.share_pct);
    setLiving(kid.covers_living);
  }, [kid.cost_level, kid.share_pct, kid.covers_living]); // eslint-disable-line react-hooks/exhaustive-deps
  const c = choiceOf(kid, { level, share_pct: share, covers_living: living });
  const line = useLine(c, kid.label, kid.account_id !== null, table);
  const id = `kid-${kid.id}`;
  return (
    <section className="card prof-card__step" aria-labelledby={`${id}-h`}>
      <h3 id={`${id}-h`}>{COLLEGE_FROM.replace('{name}', kid.label).replace('{year}', String(kid.college_start_year))}</h3>
      <fieldset className="field plain-fieldset">
        <legend className="field__label">{SCHOOL}</legend>
        <div className="ob-radios">
          {SCHOOL_ORDER.map((l) => (
            <label key={l} className="radio-row">
              <input type="radio" name={`${id}-school`} checked={level === l} onChange={() => { setLevel(l); save({ cost_level: l }); }} />
              <span>{SCHOOLS[l]}</span>
            </label>
          ))}
        </div>
        {level === 'not_sure' && <p className="field__hint">{NOT_SURE_NOTE}</p>}
      </fieldset>
      <label className="field kid-share">
        <span className="field__label">{YOUR_SHARE}</span>
        <span className="kid-share__row">
          <input type="range" min={0} max={100} step={10} value={share} aria-valuetext={`${share}%`}
            onChange={(e) => { const v = Number(e.target.value); setShare(v); save({ share_pct: v }, 300); }} />
          <output>{`${share}%`}</output>
        </span>
      </label>
      <fieldset className="field plain-fieldset">
        <legend className="field__label">{LIVING}</legend>
        <div className="ob-radios">
          {([[true, LIVING_IN], [false, LIVING_OUT]] as const).map(([v, text]) => (
            <label key={text} className="radio-row">
              <input type="radio" name={`${id}-living`} checked={living === v} onChange={() => { setLiving(v); save({ covers_living: v }); }} />
              <span>{text}</span>
            </label>
          ))}
        </div>
      </fieldset>
      <SavedUndo show={!!undo} onUndo={() => void undoIt()} />
      <p className="kid-line" aria-live="polite">{line}</p>
      {error && <Notice tone="error">{error}</Notice>}
    </section>
  );
}

export function Cover(_: BodyProps) {
  const kids = useChildren();
  if (kids.error) return <Notice tone="error">{kids.error.message}</Notice>;
  if (!kids.data) return <Skeleton lines={4} />;
  const { college } = kids.data;
  return (
    <div className="stack">
      {kids.data.children.map((k) => (outlook(choiceOf(k), planYear(), college).years === 0
        ? <p key={k.id} className="muted">{PAST_AGE.replace('{name}', k.label)}</p>
        : <KidCover key={k.id} kid={k} table={college} />))}
    </div>
  );
}
