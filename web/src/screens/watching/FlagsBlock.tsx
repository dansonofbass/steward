import { ChevronRight, CircleCheck, Flag, MailX } from 'lucide-react';
import { useCanEdit } from '../../book/BookContext';
import { Link } from '../../book/links';
import { Card } from '../../ui/Card';
import { Notice } from '../../ui/Notice';
import { Skeleton } from '../../ui/Skeleton';
import { fill } from '../inventory/format';
import { useFlags, type FlagRow } from './api';
import * as C from './copy';
import { FlagRowLink } from './FlagRow';
import { UrgentMarkIcon } from './marks';
import './watching.css';

const leftover = (r: FlagRow) =>
  `${r.check_label}: ${r.title}${r.status === 'open' ? '' : `, ${r.status_label}${r.note_by ? ` (${r.note_by})` : ''}`}`;

/** The top of a parent book's Home (inventory decision 1; README screen 1). */
export function FlagsBlock() {
  const q = useFlags('open');
  const canEdit = useCanEdit();
  if (q.isPending) return <Card><Skeleton lines={3} /></Card>;
  if (q.isError) return <Notice tone="error"><p>{q.error.message}</p></Notice>;
  const list = q.data.pages[0];
  const rows = list.flags;
  const mailOff = canEdit && list.mail_ready === false && (
    <p className="small muted mail-off"><MailX size={20} aria-hidden="true" />{C.MAIL_NOT_SET_UP_HOME} <Link className="link" to="/settings/watching">{C.SETTINGS_LINK}</Link></p>
  );
  if (rows.length === 0) {
    return (
      <>
        <section className="card attn" aria-label={C.LOOK_INTO}>
          <div className="attn__main">
            <CircleCheck size={20} aria-hidden="true" className="ok-mark" />
            <span><strong>{C.NOTHING_TO_LOOK_INTO}</strong> <span className="muted">· {list.ran ? list.ran.home_empty : C.NOT_RUN_YET}</span></span>
          </div>
          <Link className="btn btn--quiet" to="/look-into?show=done"><span className="btn__content"><span>{C.DONE_FLAGS}</span><ChevronRight size={20} aria-hidden="true" /></span></Link>
        </section>
        {mailOff}
      </>
    );
  }
  const urgent = rows.filter((r) => r.urgent).length;
  const rest = rows.slice(5);
  return (
    <>
      <section className="card flags" aria-label={C.LOOK_INTO}>
        <div className="flags__head">
          <h2><Flag size={20} aria-hidden="true" />{C.LOOK_INTO} <span className="count-pill">{rows.length}</span></h2>
          <span className="row-actions">
            {urgent > 0 && <span className="urg"><UrgentMarkIcon />{fill(C.N_URGENT, { n: urgent })}</span>}
            {list.ran && <span className="small muted">{list.ran.short}</span>}
          </span>
        </div>
        {rows.slice(0, 5).map((r) => <FlagRowLink key={r.id} row={r} compact />)}
        <div className="flags__foot">
          {rest.length > 0 && (
            <span className="small muted">
              {rest.length <= 2 ? fill(C.N_MORE, { n: rest.length, list: rest.map(leftover).join('; ') }) : fill(C.N_MORE_ONLY, { n: rest.length })}
            </span>
          )}
          <Link className="link" to="/look-into">{fill(C.SEE_ALL_N, { n: rows.length })}<ChevronRight size={20} aria-hidden="true" /></Link>
        </div>
      </section>
      {mailOff}
    </>
  );
}
