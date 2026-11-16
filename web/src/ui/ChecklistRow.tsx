import { ChevronRight, Circle, CircleAlert, CircleCheck } from 'lucide-react';
import type { ReactNode } from 'react';
import { Link } from '../book/links';
import './ChecklistRow.css';

type Props = {
  done: boolean; needs?: boolean; title: ReactNode; detail?: ReactNode;
  /** The one-word action at the end of the row. A row with neither `to` nor `onClick` shows it as plain text. */
  go?: string; to?: string; onClick?: () => void; expanded?: boolean;
  /** The row's state in words, for a screen reader; the icon alone says it to the eye. Required, so no row is left
   *  with a state only its hidden icon shows (the gate's THO-2 class). Not repeated when `go` already says it. */
  status: string; testId?: string; tag?: ReactNode;
};

/** One row of a checklist (Set up Steward, Get Steward ready): a link, a button that opens something, or plain text. */
export function ChecklistRow({ done, needs = false, title, detail, go, to, onClick, expanded, status, testId, tag }: Props) {
  const acts = Boolean(to || onClick);
  const Icon = done ? CircleCheck : needs ? CircleAlert : Circle;
  const cls = `setup__row${done ? ' is-done' : ''}${needs ? ' is-needs' : ''}${acts ? '' : ' is-still'}`;
  const body = (
    <>
      <Icon className="i" size={24} aria-hidden="true" />
      <span className="setup__title">{title}{tag}</span>
      {status !== go && <span className="setup__status">{status}</span>}
      {detail && <span className="setup__detail">{detail}</span>}
      {go && (acts
        ? <span className="setup__go"><span>{go}</span><ChevronRight className="i" size={20} aria-hidden="true" /></span>
        : <span className="setup__go">{go}</span>)}
    </>
  );
  if (to) return <Link className={cls} to={to} data-testid={testId}>{body}</Link>;
  if (onClick) return <button type="button" className={cls} onClick={onClick} aria-expanded={expanded} data-testid={testId}>{body}</button>;
  return <div className={cls} data-testid={testId}>{body}</div>;
}
