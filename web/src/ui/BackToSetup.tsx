import { ArrowLeft } from 'lucide-react';
import { Link } from '../book/links';
import './BackToSetup.css';

export const BACK_TO_SETUP = 'Back to setup';

/** Import and Review, opened from the first run (?from=welcome), lead back to it: to the money step, or to the extras
 *  with the sorts noted as done (the extras play their hop). */
export function BackToSetup({ step }: { step: 'money' | 'extras' }) {
  return (
    <Link className="link back-to-setup" to={`/welcome?step=${step}`} state={step === 'extras' ? { setupDone: 'sort' } : undefined}>
      <ArrowLeft className="i" size={20} aria-hidden="true" />{BACK_TO_SETUP}
    </Link>
  );
}
