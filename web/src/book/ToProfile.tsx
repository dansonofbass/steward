import { useLocation, useParams } from 'react-router-dom';
import { OLD_STEP_SECTION, sectionPath } from '../lib/profileSections';
import { Navigate } from './links';

/** Set up Steward and Settings › Profile are Profile now (P2): an old step opens the section that holds it; ?from= stays. */
export function ToProfile() {
  const { step } = useParams();
  const { search } = useLocation();
  const section = step ? OLD_STEP_SECTION[step] : undefined;
  return <Navigate to={`${section ? sectionPath(section) : '/profile'}${search}`} replace />;
}
