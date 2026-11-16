import { useParams, useSearchParams } from 'react-router-dom';
import { useProfile } from '../../api/profile';
import { useCanEdit } from '../../book/BookContext';
import { Navigate } from '../../book/links';
import { TRY_AGAIN } from '../../lib/copy';
import { SECTION_STEPS, isFinished, isSection, sectionPath } from '../../lib/profileSections';
import { Button } from '../../ui/Button';
import { Notice } from '../../ui/Notice';
import { Skeleton } from '../../ui/Skeleton';
import { Flow } from './Flow';
import { ProfilePage } from './ProfilePage';
import { SECTIONS } from './registry';
import { SectionCard } from './SectionCard';
import './profile.css';

/** /profile, /profile/{section} and /profile/{section}/{step} (spec, Routes): household books only (routes.tsx). */
export default function Profile() {
  const { section, step } = useParams();
  const [params] = useSearchParams();
  const profile = useProfile();
  const canEdit = useCanEdit();
  const from = params.get('from') === 'plan' ? ('plan' as const) : undefined;
  if (profile.isError) {
    return (
      <div className="screen profile">
        <Notice tone="error"><p>{profile.error.message}</p><Button variant="quiet" onClick={() => profile.refetch()}>{TRY_AGAIN}</Button></Notice>
      </div>
    );
  }
  if (!profile.data) {
    return <div className="screen profile" aria-busy="true"><div className="card prof-rows">{[0, 1, 2, 3, 4].map((i) => <Skeleton key={i} lines={2} />)}</div></div>;
  }
  if (section === undefined) return <ProfilePage profile={profile.data} />;
  const def = isSection(section) ? SECTIONS[section] : undefined;
  if (!isSection(section) || !def) return <Navigate to="/profile" replace />;
  const state = profile.data.sections.find((s) => s.key === section)!;
  if (step === undefined) {
    if (isFinished(state.status) || !canEdit) return <SectionCard key={section} section={section} def={def} profile={profile.data} />;
    return <Navigate to={sectionPath(section, state.resume_step ?? SECTION_STEPS[section][0], from)} replace />;
  }
  if (!canEdit || !def.steps.some((s) => s.key === step)) return <Navigate to={sectionPath(section, null, from)} replace />;
  return <Flow key={`${section}/${step}`} section={section} def={def} step={step} profile={profile.data} />;
}
