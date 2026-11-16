import { useRef, useState } from 'react';
import { Link, useNavigate } from '../../book/links';
import { soundOn } from '../../lib/celebrations';
import { nextLine } from '../../lib/lines';
import { momentAllowed } from '../../lib/momentAllowed';
import { Button } from '../../ui/Button';
import { OakTree } from '../../ui/OakTree';
import { useAcornMotion } from '../../ui/useMoment';
import { useReady } from '../ready/api';
import * as C from './copy';

/** The acorn planted at stage 0 (the tree's growth is the milestones'), the line, a link to Get Steward ready only
 *  while a row needs them, and the way Home. */
export function Planted() {
  const ref = useRef<SVGSVGElement>(null);
  const [line] = useState(() => nextLine('planted'));
  const navigate = useNavigate();
  const ready = useReady();
  const allowed = momentAllowed('planted', { parent: false });
  useAcornMotion(ref, allowed.motion ? 'plant' : null, allowed.sound && soundOn());
  const need = ready.data?.need ?? 0;
  return (
    <section className="welcome__step welcome__planted" aria-labelledby="welcome-planted-h">
      <OakTree stage={0} ref={ref} size={96} label={C.PLANTED} />
      <h1 id="welcome-planted-h" className="welcome__title">{C.PLANTED}</h1>
      {allowed.line && <p className="welcome__lede">{line}</p>}
      {need > 0 && <Link className="link" to="/settings/ready">{C.toGo(need)}</Link>}
      <Button onClick={() => navigate('/', { replace: true })}>{C.GO_HOME}</Button>
    </section>
  );
}
