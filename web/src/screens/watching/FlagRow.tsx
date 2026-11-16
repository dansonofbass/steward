import { Link } from '../../book/links';
import { money } from '../../lib/format';
import type { FlagRow } from './api';
import { CHECK_ICONS, FlagStatusMark, UrgentMark } from './marks';
import './watching.css';

/** One flag in Look into or on Home (README screens 1 and 2). On Home (compact) an Open flag shows no status mark and no note. */
export function FlagRowLink({ row, compact = false }: { row: FlagRow; compact?: boolean }) {
  const Icon = CHECK_ICONS[row.check];
  const cls = ['frow', row.urgent ? 'is-urgent' : '', row.done ? 'is-done' : ''].filter(Boolean).join(' ');
  return (
    <Link className={cls} to={`/look-into/${row.id}`} data-testid="flag-row">
      <Icon size={20} aria-hidden="true" />
      <span className="frow__main">
        <span className="frow__what"><b>{row.check_label}:</b> {row.summary}</span>
        <span className="frow__meta">{row.urgent && <UrgentMark />}<span>{row.place}</span><span>{row.when}</span></span>
        {row.note && !compact && <span className="frow__note">{row.note_by ? `${row.note_by}: ` : ''}"{row.note}"</span>}
      </span>
      <span className="frow__side">
        {!(compact && row.status === 'open') && <FlagStatusMark status={row.status} label={row.status_label} by={compact ? null : row.by} />}
        <span className="small muted">{row.flagged}</span>
      </span>
      <span className="money money--m">{row.amount_cents !== null ? money(row.amount_cents) : ''}</span>
    </Link>
  );
}
