import { ListChecks } from 'lucide-react';
import { Fragment, useState } from 'react';
import { useBook } from '../../book/BookContext';
import { useNavigate } from '../../book/links';
import { REVIEW } from '../../lib/copy';
import { Acorn } from '../../ui/Acorn';
import { Button } from '../../ui/Button';
import { CelebrationSwitches } from '../settings/Appearance';
import { markWelcome, type WelcomeState } from './api';
import * as C from './copy';
import './welcome.css';

/** A partner's welcome (guided setup spec 7.2 to 7.4): what this is, their own switches, their name on their work.
 *  Three screens in local state. Skip and Go to Home mark it seen (not on a replay) and go Home. The acorn sits still,
 *  and only in a household book. */
export function PartnerWelcome({ state, again }: { state: WelcomeState; again: boolean }) {
  const book = useBook();
  const navigate = useNavigate();
  const [n, setN] = useState(0);
  const manager = (book?.role ?? 'manager') === 'manager';
  const parent = book?.kind === 'parent';
  const name = book?.name ?? '';

  const leave = async () => {
    if (!again && book) { try { await markWelcome(book.slug); } catch { /* the welcome comes back next time */ } }
    navigate('/', { replace: true });
  };
  const last = n === 2;

  return (
    <div className="screen welcome">
      <p className="welcome__skip"><Button variant="quiet" onClick={() => void leave()}>{C.SKIP}</Button></p>
      {n === 0 && (
        <section className="welcome__hello" aria-labelledby="pw-h">
          {!parent && <Acorn face="win" size={72} className="welcome__acorn" />}
          <h1 id="pw-h" className="welcome__title">{C.welcomeTo(name)}</h1>
          <p className="welcome__lede">{parent ? C.keepsParent(state.inviter, name) : C.keepsHousehold(state.inviter)}</p>
          <p className="muted">{manager ? C.SEE_AND_CHANGE : C.SEE_ONLY}</p>
        </section>
      )}
      {n === 1 && (
        <section className="welcome__step" aria-labelledby="pw-h">
          <h1 id="pw-h" className="welcome__title">{C.SWITCHES}</h1>
          <CelebrationSwitches />
          <p className="muted">{C.YOURS_ALONE}</p>
        </section>
      )}
      {n === 2 && (
        <section className="welcome__step" aria-labelledby="pw-h">
          <h1 id="pw-h" className="welcome__title">{C.NAME_ON_WORK}</h1>
          <p>{manager ? withReview(C.MANAGER_WORK) : C.VIEWER_WORK}</p>
        </section>
      )}
      <div className="welcome__actions">
        <Button onClick={() => (last ? void leave() : setN(n + 1))}>{last ? C.GO_HOME : C.NEXT}</Button>
      </div>
    </div>
  );
}

/** {review} is the Review nav icon followed by the word Review. */
function withReview(text: string) {
  const [before, after] = text.split('{review}');
  return (
    <Fragment>
      {before}<span className="welcome__nav"><ListChecks className="i" size={16} aria-hidden /> <strong>{REVIEW}</strong></span>{after}
    </Fragment>
  );
}
