import {
  Briefcase, Calendar, ChevronDown, Gift, GraduationCap, PiggyBank, ShieldCheck, User, Wallet, type LucideIcon,
} from 'lucide-react';
import { useId, useState } from 'react';
import { Link } from '../../book/links';
import { dollars } from '../../lib/format';
import { radioKeys, radioTab } from '../../lib/radioKeys';
import { Button } from '../../ui/Button';
import type { CostLevel, Impact, LeverField, LeverKey, LeverSpec, LeverValue, LeverValues, PlanCollege } from './api';
import {
  CHANGE_SUGGESTION, CHANGE_IN_PROFILE, CHANGED, CUT_FROM_2034, DONE, FULL_SS_NOTE, IN_USE, KID_SHARE_LINE, LEVEL_A_YEAR, LEVEL_NAME, LEVELS, LIVING_WORD, NO_CUT, NO_HISTORY_FOOT,
  NO_HISTORY_YET, SAVED_PLAN_VALUE, SUGGESTION, TRY_THIS, USE_LAST_YEAR, WORKING_IT_OUT, YOU_SET_THIS_SUGGESTION,
} from './copy';
import { UNPINNABLE, amountText, atSuggestion, effectClass, extrasFor, fromHistory, scaleLabels, tryText, type RowCtx } from './levers';
import { Slider } from './Slider';
import { Sep } from '../../ui/Sep';

const ICONS: Record<LeverKey, LucideIcon> = {
  save_more: PiggyBank, spending: Wallet, consulting: Briefcase, gift: Gift, spouse_earnings: User,
  jr_claim: Calendar, spouse_claim: Calendar, college: GraduationCap, full_ss: ShieldCheck,
};

export type RowProps = {
  spec: LeverSpec; impact: Impact | undefined; childImpacts: Impact[]; impactsPending: boolean;
  assumed: LeverValues; trial: LeverValues; saved: LeverValues;
  changed: boolean; pinned: boolean; note: string | undefined; open: boolean; onToggle: () => void;
  onAssumed: (field: LeverField, v: LeverValue) => void; onTry: (field: LeverField, v: LeverValue) => void;
  onTryThis: () => void; onUnpin: () => void;
  ctx: RowCtx;
};

function TryThis({ p }: { p: RowProps }) {
  return (
    <Button variant="quiet" disabled={atSuggestion(p.spec.key, p.assumed, p.trial)} onClick={p.onTryThis} data-testid={`trythis-${p.spec.key}`}>
      {TRY_THIS}
    </Button>
  );
}

function Extras({ p, values, who, set }: { p: RowProps; values: LeverValues; who: string; set: (f: LeverField, v: LeverValue) => void }) {
  const extras = extrasFor(p.spec.key, p.ctx);
  if (extras.length === 0) return null;
  return (
    <div className="pair">
      {extras.map((x) => {
        const v = values[x.field] as number;
        return (
          <label key={x.field} className="mini-field">
            <span>{x.label}</span>
            <select aria-label={`${who}: ${x.label}`} value={String(v)} onChange={(e) => set(x.field, Number(e.target.value))}>
              {!x.options.includes(v) && <option value={String(v)}>{v}</option>}
              {x.options.map((o) => <option key={o} value={String(o)}>{o}</option>)}
            </select>
          </label>
        );
      })}
    </div>
  );
}

function SwitchBody(p: RowProps) {
  const value = p.assumed.full_ss_benefits;
  return (
    <>
      <div className="slider">
        <div className="seg" role="radiogroup" aria-label={p.spec.label} onKeyDown={radioKeys}>
          {([[false, CUT_FROM_2034], [true, NO_CUT]] as const).map(([v, text]) => (
            <button key={text} type="button" role="radio" aria-checked={value === v} tabIndex={radioTab(value === v)} className={value === v ? 'is-on' : ''}
              onClick={() => p.onAssumed('full_ss_benefits', v)}>{text}</button>
          ))}
        </div>
        <div className="slider__actions"><TryThis p={p} /></div>
      </div>
      <p className="small muted">{FULL_SS_NOTE}</p>
    </>
  );
}

function yearCost(c: PlanCollege, level: CostLevel, i: number): number {
  const lv = c.levels[level];
  const kid = c.children[i];
  const cents = (lv.tuition_fees_cents + (kid?.covers_living === false ? 0 : lv.living_cents)) * ((kid?.share_pct ?? 100) / 100);
  return Math.round(cents / 100_000) * 100_000;
}

function CollegeBody(p: RowProps) {
  const a = p.assumed.college_levels ?? [];
  const at = (list: CostLevel[], i: number, v: CostLevel) => list.map((l, j) => (j === i ? v : l));
  const college = p.ctx.college;
  return (
    <>
      {p.ctx.childLabels.map((label, i) => {
        const effect = p.childImpacts.find((x) => x.child_label === label);
        const kid = college?.children[i];
        const own = kid && (kid.share_pct !== 100 || !kid.covers_living);
        return (
          <div key={`${label}-${i}`} className="college-child">
            <label className="mini-field">
              <span>{label}</span>
              <select aria-label={`${p.spec.label}: ${label}`} value={a[i]} onChange={(e) => p.onAssumed('college_levels', at(a, i, e.target.value as CostLevel))}>
                {LEVELS.map((l) => (
                  <option key={l} value={l}>
                    {college ? LEVEL_A_YEAR.replace('{level}', LEVEL_NAME[l]).replace('{cost}', dollars(yearCost(college, l, i))) : LEVEL_NAME[l]}
                  </option>
                ))}
              </select>
            </label>
            {own && (
              <p className="small muted">
                {KID_SHARE_LINE.replace('{share}', String(kid.share_pct)).replace('{living}', kid.covers_living ? LIVING_WORD.in : LIVING_WORD.out)}{' '}
                <Link className="link" to="/profile/kids"><strong>{CHANGE_IN_PROFILE}</strong></Link>
              </p>
            )}
            {effect && <p className="small muted">{effect.text}</p>}
          </div>
        );
      })}
      <div className="slider__actions"><TryThis p={p} /></div>
    </>
  );
}

/** The one slider is the assumed value. "Change suggestion" swaps it, in place, for the try value (which pins it). */
function RangeBody(p: RowProps) {
  const [suggesting, setSuggesting] = useState(false);
  const field = p.spec.fields[0];
  const scale = p.spec.scale!;
  const labels = scaleLabels(p.spec);
  const counted = p.assumed[field] as number;
  const savedValue = p.saved[field] as number;
  if (suggesting) {
    const trial = p.trial[field] as number;
    return (
      <>
        <Slider variant="try" label={SUGGESTION} lever={p.spec.label} value={trial} scale={scale} labels={labels}
          valueText={amountText(field, trial)} onChange={(v) => p.onTry(field, v)} testId={`suggest-${p.spec.key}`}
          note={p.pinned ? YOU_SET_THIS_SUGGESTION : undefined}
          actions={<>
            <Button variant="quiet" onClick={() => setSuggesting(false)}>{DONE}</Button>
            {UNPINNABLE.includes(p.spec.key) && p.pinned && <button type="button" className="link link--quiet" onClick={p.onUnpin}>{USE_LAST_YEAR}</button>}
          </>} />
        <Extras p={p} values={p.trial} who={SUGGESTION} set={p.onTry} />
      </>
    );
  }
  return (
    <>
      <Slider lever={p.spec.label} value={counted} scale={scale} labels={labels} valueText={amountText(field, counted)}
        saved={savedValue !== counted ? SAVED_PLAN_VALUE.replace('{value}', amountText(field, savedValue)) : undefined}
        ghost={savedValue} onChange={(v) => p.onAssumed(field, v)} testId={`slider-${p.spec.key}`}
        note={p.note ? NO_HISTORY_FOOT : undefined}
        actions={<>
          <TryThis p={p} />
          <button type="button" className="link link--quiet" onClick={() => setSuggesting(true)}>{CHANGE_SUGGESTION}</button>
        </>} />
      {counted > 0 && <Extras p={p} values={p.assumed} who={p.spec.label} set={p.onAssumed} />}
    </>
  );
}

export function LeverRow(p: RowProps) {
  const Icon = ICONS[p.spec.key];
  const bodyId = useId();
  // At its suggestion the impact is zero by definition, so a changed row says "In use" instead of "No change".
  const inUse = p.changed && atSuggestion(p.spec.key, p.assumed, p.trial);
  const effectCls = inUse ? 'is-inuse' : `${effectClass(p.impact)}${p.impactsPending ? ' is-stale' : ''}`;
  return (
    <div className={`lever${p.open ? ' is-open' : ''}${p.changed ? ' is-changed' : ''}`} data-testid={`lever-${p.spec.key}`}>
      <button type="button" className="lever__head" aria-expanded={p.open} aria-controls={bodyId} onClick={p.onToggle}>
        <Icon className="i" size={24} aria-hidden="true" />
        <span className="lever__name">
          {p.spec.label}
          {p.note && <span className="tag">{NO_HISTORY_YET}</span>}
          {p.changed && <span className="tag tag--changed">{CHANGED}</span>}
        </span>
        <span className="lever__try">
          {tryText(p.spec.key, p.assumed, p.trial, p.ctx, fromHistory(p.spec.key, p.pinned, p.note))}
          <Sep className="sep" />
          <span className={`lever__effect ${effectCls}`}>{inUse ? IN_USE : p.impact?.text ?? WORKING_IT_OUT}</span>
        </span>
        <ChevronDown className="i" size={20} aria-hidden="true" />
      </button>
      <div id={bodyId} className="lever__body" hidden={!p.open}>
        {p.open && (p.spec.kind === 'switch' ? <SwitchBody {...p} /> : p.spec.kind === 'level' ? <CollegeBody {...p} /> : <RangeBody {...p} />)}
      </div>
    </div>
  );
}
