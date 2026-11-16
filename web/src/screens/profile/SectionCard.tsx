import { ArrowLeft, History } from 'lucide-react';
import { useSearchParams } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { confirmMine, refreshProfile, type ProfileState } from '../../api/profile';
import { useCanEdit } from '../../book/BookContext';
import { useState } from 'react';
import { Link } from '../../book/links';
import { SECTION_NAME, type SectionKey } from '../../lib/profileSections';
import { Button } from '../../ui/Button';
import { Notice } from '../../ui/Notice';
import { failure } from '../settings/shared';
import { CONFIRM, EARLIER_VALUES, PLAN, TITLE } from './copy';
import { EarlierValues } from './EarlierValues';
import { FieldCtx } from './field';
import { sectionFacts } from './history';
import { confirmOnly, savedByLine, type SectionDef } from './sections';

const noRegister = () => () => {};

/** /profile/{section} once it is done: the same fields as the flow, as one card, each edited in place (spec, The card). */
export function SectionCard({ section, def, profile }: { section: SectionKey; def: SectionDef; profile: ProfileState }) {
  const canEdit = useCanEdit();
  const qc = useQueryClient();
  const [params] = useSearchParams();
  const fromPlan = params.get('from') === 'plan';
  const state = profile.sections.find((s) => s.key === section)!;
  const lines = def.useSummary(profile) ?? [];
  const saved = savedByLine(state, new Date());
  const [problem, setProblem] = useState<string | null>(null);
  const fields = sectionFacts(section, profile.names);
  const [earlier, setEarlier] = useState(false);
  const confirming = section === 'you' && canEdit && confirmOnly(profile);
  return (
    <FieldCtx.Provider value={{ mode: 'card', register: noRegister, canEdit }}>
      <div className="screen profile prof-card">
        <Link className="link" to={fromPlan ? '/plan' : '/profile'}><ArrowLeft className="i" size={20} aria-hidden="true" />{fromPlan ? PLAN : TITLE}</Link>
        <h1>{SECTION_NAME[section]}</h1>
        {saved && <p className="saved-note">{saved}</p>}
        {lines.map((l) => <p key={l} className="prof-card__sum">{l}</p>)}
        {fields && canEdit && <button type="button" className="link" onClick={() => setEarlier(true)}><History className="i" size={20} aria-hidden="true" />{EARLIER_VALUES}</button>}
        {fields && <EarlierValues open={earlier} onClose={() => setEarlier(false)} fields={fields} />}
        {def.Card ? <def.Card profile={profile} /> : def.steps.map((s) => (
          <section key={s.key} className="card prof-card__step" aria-labelledby={`prof-${s.key}-h`}>
            <h2 id={`prof-${s.key}-h`}>{s.title(profile.names, profile)}</h2>
            <s.Body profile={profile} />
          </section>
        ))}
        {confirming && <Button onClick={() => { setProblem(null); refreshProfile(qc, confirmMine()).catch((e) => setProblem(failure(e))); }}>{CONFIRM}</Button>}
        {problem && <Notice tone="error">{problem}</Notice>}
      </div>
    </FieldCtx.Provider>
  );
}
