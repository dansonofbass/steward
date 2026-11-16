import { Users } from 'lucide-react';
import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useFacts, useMe } from '../../../api/hooks';
import { renameMe, type ProfileState, type Role } from '../../../api/profile';
import { dateLabel, dollars, localYmd } from '../../../lib/format';
import { Notice } from '../../../ui/Notice';
import { Skeleton } from '../../../ui/Skeleton';
import { dollarsText, fromHundredths, toHundredths } from '../../settings/money';
import { STATES } from '../../settings/states';
import { saveFact, savedNote } from '../api';
import {
  A_YEAR, BIRTHDAY_NEEDED, BIRTHDAY_PAST, CARD_PAY, CARD_YOU, CHOOSE_STATE, type Filing, FILING, FILING_NAME, FILING_NEEDED, FILING_ORDER, MATCH_ADDS, MATCH_CAP, MATCH_RATE, NAME_NEEDED, ONLY_THEY, PAY_K401, PAY_ROTH, PAY_SALARY, PAY_WHY, PERCENT_RANGE, ROTH_HINT, SALARY_NEEDED, STATE, STATE_NEEDED, STEP_PAY, STEP_TAXES, STEP_YOU, THEIR_BIRTHDAY, THEIR_NAME, YOUR_BIRTHDAY, YOUR_NAME, YOUR_NAME_HINT,
} from '../copy';
import { ProfileField } from '../field';
import { confirmOnly, type BodyProps, type SectionDef } from '../sections';

const self = (p: ProfileState): Role => p.me.role ?? 'jr';
const partner = (p: ProfileState): Role => (self(p) === 'jr' ? 'spouse' : 'jr');
const todayYmd = () => localYmd(new Date().toISOString());

function birthday(t: string): string | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(t)) return BIRTHDAY_NEEDED;
  return t >= todayYmd() ? BIRTHDAY_PAST : null;
}

function percent(t: string): string | null {
  const p = toHundredths(t);
  return 'error' in p || p.value < 0 || p.value > 10_000 ? PERCENT_RANGE : null;
}

const bp = (t: string) => String((toHundredths(t) as { value: number }).value);

function useFactsReady() {
  const facts = useFacts();
  const me = useMe();
  const ready = facts.data && me.data;
  return { facts, me, f: ready ? facts.data!.facts : undefined, name: me.data?.user.display_name ?? '' };
}

function Wait({ error }: { error: Error | null }) {
  return error ? <Notice tone="error">{error.message}</Notice> : <Skeleton lines={2} />;
}

function YouStep({ profile }: BodyProps) {
  const { facts, me, f, name } = useFactsReady();
  const qc = useQueryClient();
  if (!f) return <Wait error={facts.error ?? me.error} />;
  const role = profile.me.role;
  const who = self(profile);
  const mine = confirmOnly(profile);
  const dob = f[`${who}.dob`]?.value ?? '';
  return (
    <div className="stack">
      {role && (
        <ProfileField label={YOUR_NAME} hint={YOUR_NAME_HINT} input="text" maxLength={80} text={name} shown={name} highlight={mine}
          check={(t) => (t.trim() === '' || t.trim().length > 80 ? NAME_NEEDED : null)}
          save={async (t) => { await renameMe(t.trim()); await qc.invalidateQueries({ queryKey: ['me'] }); return null; }} />
      )}
      <ProfileField label={role ? YOUR_BIRTHDAY : THEIR_BIRTHDAY.replace('{name}', profile.names[who])} input="date" text={dob}
        shown={dob ? dateLabel(dob, new Date()) : ''} highlight={mine} check={birthday}
        save={(t) => saveFact(`${who}.dob`, t, savedNote(name || profile.names[who]))} />
    </div>
  );
}

function PartnerStep({ profile }: BodyProps) {
  const { facts, me, f, name } = useFactsReady();
  if (!f) return <Wait error={facts.error ?? me.error} />;
  const who = partner(profile);
  const them = profile.names[who];
  const dob = f[`${who}.dob`]?.value ?? '';
  return (
    <div className="stack">
      {profile.people[who] && (
        <ProfileField label={THEIR_NAME.replace('{name}', them)} input="text" text={them} shown={them}
          readOnly={ONLY_THEY.replace('{name}', them)} check={() => null} save={async () => null} />
      )}
      <ProfileField label={THEIR_BIRTHDAY.replace('{name}', them)} input="date" text={dob} shown={dob ? dateLabel(dob, new Date()) : ''}
        check={birthday} save={(t) => saveFact(`${who}.dob`, t, savedNote(name || them))} />
    </div>
  );
}

function TaxesStep(_: BodyProps) {
  const { facts, me, f, name } = useFactsReady();
  if (!f) return <Wait error={facts.error ?? me.error} />;
  const state = f.state?.value ?? '';
  const filing = (f.filing_status?.value ?? '') as Filing | '';
  return (
    <div className="stack">
      <ProfileField label={STATE} input="select" text={state} shown={STATES.find(([c]) => c === state)?.[1] ?? ''}
        options={[{ value: '', label: CHOOSE_STATE }, ...STATES.map(([c, l]) => ({ value: c, label: `${l} (${c})` }))]}
        check={(t) => (t ? null : STATE_NEEDED)} save={(t) => saveFact('state', t, savedNote(name))} />
      <ProfileField label={FILING} input="radios" text={filing} shown={filing ? FILING_NAME[filing] : ''}
        options={FILING_ORDER.map((x) => ({ value: x, label: FILING_NAME[x] }))}
        check={(t) => (t ? null : FILING_NEEDED)} save={(t) => saveFact('filing_status', t, savedNote(name))} />
    </div>
  );
}

function PayStep({ profile }: BodyProps) {
  const { facts, me, f, name } = useFactsReady();
  const [live, setLive] = useState<Record<string, string>>({});
  if (!f) return <Wait error={facts.error ?? me.error} />;
  const jr = profile.names.jr;
  const text = (k: string) => (f[k] ? fromHundredths(Number(f[k].value)) : '');
  const money = (k: string) => (f[k] ? dollarsText(Number(f[k].value)) : '');
  const now = (k: string, fallback: string) => live[k] ?? fallback;
  const salary = toHundredths(now('salary', money('jr.salary_cents')));
  const k401 = toHundredths(now('k401', text('jr.k401_pct_bp')));
  const rate = toHundredths(now('rate', text('employer.match_rate_bp')));
  const cap = toHundredths(now('cap', text('employer.match_cap_bp')));
  const ok = (p: ReturnType<typeof toHundredths>): p is { value: number } => !('error' in p);
  const contribution = ok(salary) && ok(k401) ? Math.round((salary.value * k401.value) / 10_000) : null;
  const match = ok(salary) && ok(k401) && ok(rate) && ok(cap)
    ? Math.round((((salary.value * Math.min(k401.value, cap.value)) / 10_000) * rate.value) / 10_000) : null;
  const follow = (k: string) => (t: string) => setLive((l) => ({ ...l, [k]: t }));
  const note = savedNote(name);
  const pct = (k: string) => ({
    input: 'percent' as const, text: text(k), shown: f[k] ? `${fromHundredths(Number(f[k].value))}%` : '', check: percent,
    save: (t: string) => saveFact(k, bp(t), note),
  });
  return (
    <div className="stack">
      <p className="prof-why">{PAY_WHY}</p>
      <ProfileField label={PAY_SALARY.replace('{jr}', jr)} input="money" post={A_YEAR} text={money('jr.salary_cents')}
        shown={f['jr.salary_cents'] ? `${dollars(Number(f['jr.salary_cents'].value))} ${A_YEAR}` : ''} onText={follow('salary')}
        check={(t) => { const p = toHundredths(t); return 'error' in p || p.value <= 0 ? SALARY_NEEDED.replace('{jr}', jr) : null; }}
        save={(t) => saveFact('jr.salary_cents', bp(t), note)} />
      <ProfileField label={PAY_K401} hint={contribution !== null ? `${dollars(contribution)} ${A_YEAR}.` : undefined} {...pct('jr.k401_pct_bp')} onText={follow('k401')} />
      <ProfileField label={PAY_ROTH} hint={ROTH_HINT} {...pct('jr.k401_roth_share_bp')} />
      <ProfileField label={MATCH_RATE} {...pct('employer.match_rate_bp')} onText={follow('rate')} />
      <ProfileField label={MATCH_CAP} {...pct('employer.match_cap_bp')} onText={follow('cap')} />
      {match !== null && <p className="small muted">{MATCH_ADDS.replace('{amount}', dollars(match))}</p>}
    </div>
  );
}

function useYouSummary(profile: ProfileState): string[] | null {
  const f = useFacts().data?.facts;
  if (!f) return null;
  const state = STATES.find(([c]) => c === f.state?.value)?.[1] ?? '';
  const filing = f.filing_status ? FILING_NAME[f.filing_status.value as Filing] ?? '' : '';
  const lines = [CARD_YOU.replace('{jr}', profile.names.jr).replace('{spouse}', profile.names.spouse).replace('{state}', state).replace('{filing}', filing)];
  if (f['jr.salary_cents'] && f['jr.k401_pct_bp']) {
    lines.push(CARD_PAY.replace('{salary}', dollars(Number(f['jr.salary_cents'].value))).replace('{pct}', fromHundredths(Number(f['jr.k401_pct_bp'].value))));
  }
  return lines;
}

/** Profile's first section (P1: About you + Pay): today's fields, components and checks, four steps. */
export const YOU_SECTION: SectionDef = {
  icon: Users,
  steps: [
    { key: 'you', title: () => STEP_YOU, Body: YouStep },
    { key: 'partner', title: (names, p) => names[partner(p)], Body: PartnerStep },
    { key: 'taxes', title: () => STEP_TAXES, Body: TaxesStep },
    { key: 'pay', title: () => STEP_PAY, Body: PayStep },
  ],
  useSummary: useYouSummary,
};
