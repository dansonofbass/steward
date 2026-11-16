import { X } from 'lucide-react';
import { useQueryClient } from '@tanstack/react-query';
import { useMemo, useRef, useState } from 'react';
import type { Account } from '../../api/types';
import { isInvestment } from '../../lib/accountKinds';
import { gatewayName } from '../../lib/gatewayName';
import { lazyScreen } from '../../lib/lazyScreen';
import { OopsAcorn } from '../../ui/OopsAcorn';
import { failure } from '../settings/shared';
import * as C from './copy';
import { isRetryable, needsLook, retryStatement, statementTag, type GatewayState, type StatementLine } from './statements';

// The layout check and row review: their own chunk, loaded when a line needs a look (P48).
const Statements = lazyScreen(() => import('./Statements'));

const escape = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
/** The gateway's name never breaks inside itself (a name like "Zebra-Box" at its hyphen). */
function unbroken(s: string) {
  const n = gatewayName();
  const forms = [...new Set([n, n.charAt(0).toUpperCase() + n.slice(1)])].map(escape).join('|');
  return s.split(new RegExp(`(${forms})`)).map((part, i) => (i % 2 === 1 ? <span key={i} className="imp-row__nb">{part}</span> : part));
}

const RETRY_TAIL = ' · ' + C.ST_TRY_AGAIN;

/** A gentle word when a holdings or loan statement sits on an account of another type; it never blocks (a parent's book
 *  often has loosely typed accounts). */
function typeNote(line: StatementLine, accounts: Account[]): string | null {
  const a = line.account_id === null ? undefined : accounts.find((x) => x.id === line.account_id);
  if (!a) return null;
  if ((line.statement_kind === 'investment' || line.statement_kind === 'retirement') && !isInvestment(a.type)) {
    return C.ST_NOT_INVESTMENT.replace('{account}', a.name);
  }
  if (line.statement_kind === 'loan' && a.type !== 'loan' && a.type !== 'mortgage') return C.ST_NOT_LOAN.replace('{account}', a.name);
  return null;
}

type Props = {
  line: StatementLine; gateway: GatewayState; accounts: Account[]; open: boolean;
  onOpen: () => void; onDone?: (to: StatementLine['state']) => void; onAccount: (value: string) => void; onRemove: (el: HTMLElement | null) => void;
  track?: <T>(p: Promise<T>) => Promise<T>;
};

/** One PDF in the batch: its name, its status in words (never colour alone), its account and ×. A line that needs a
 *  look opens in place into the layout check or row review. */
export function StatementRow({ line, gateway, accounts, open, onOpen, onDone, onAccount, onRemove, track }: Props) {
  const li = useRef<HTMLLIElement>(null);
  const qc = useQueryClient();
  const [refused, setRefused] = useState('');
  const groups = useMemo(() => {
    const m = new Map<string, Account[]>();
    for (const a of accounts) m.set(a.institution, [...(m.get(a.institution) ?? []), a]);
    return [...m.entries()];
  }, [accounts]);
  const text = statementTag(line, gateway);
  const warn = line.state === 'error' || line.state === 'off';
  const retryable = isRetryable(line);
  const [head, tail] = retryable && text.includes(RETRY_TAIL) ? text.split(RETRY_TAIL) : [text, null];
  async function retry() {
    setRefused('');
    try {
      await retryStatement(line.id);
      await qc.invalidateQueries({ queryKey: ['statements'] });
    } catch (e) {
      setRefused(failure(e));
    }
  }
  const picks = !['error', 'cleared'].includes(line.state);
  const note = picks ? typeNote(line, accounts) : null;
  return (
    <li ref={li} className="imp-row" aria-busy={line.state === 'reading' || undefined}>
      <div className="imp-row__line">
        <span className="imp-row__name">{line.name}</span>
        {line.state === 'error' && <OopsAcorn />}
        {needsLook(line)
          ? <button type="button" className={`link imp-row__tag imp-row__look${warn ? ' imp-row__tag--warn' : ''}`} aria-expanded={open} data-look={line.id}
              onClick={onOpen}>{unbroken(text)}</button>
          : tail === null
            ? <span className={`imp-row__tag${line.state === 'error' ? ' imp-row__tag--warn' : ''}${line.state === 'cleared' ? ' muted' : ''}`}>{unbroken(text)}</span>
            : (
              <span className="imp-row__tag imp-row__tag--warn">
                <span>{unbroken(head)}</span> · <button type="button" className="link imp-row__retry" onClick={() => void retry()}>{C.ST_TRY_AGAIN}</button>{tail}
              </span>
            )}
        {!picks && <span className="imp-row__pad" aria-hidden="true" />}
        {picks && (
          <select className="imp-row__account" data-account={line.id} aria-label={C.ACCOUNT_FOR.replace('{file}', line.name)} value={line.account_id ?? ''}
            onChange={(e) => onAccount(e.target.value)}>
            <option value="">{C.ACCOUNT_EMPTY}</option>
            {groups.map(([inst, list]) => (
              <optgroup key={inst} label={inst}>{list.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}</optgroup>
            ))}
          </select>
        )}
        <button type="button" className="icon-btn imp-row__remove" aria-label={C.REMOVE.replace('{file}', line.name)}
          onClick={() => onRemove(li.current)}><X size={20} aria-hidden="true" /></button>
      </div>
      {note && <p className="small muted imp-row__note">{note}</p>}
      {refused && <p className="small imp-row__tag--warn" role="alert">{refused}</p>}
      {open && needsLook(line) && <Statements line={line} onDone={onDone ?? onOpen} track={track} />}
    </li>
  );
}
