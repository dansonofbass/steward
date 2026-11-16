import { X } from 'lucide-react';
import { useMemo, useRef } from 'react';
import type { Account } from '../../api/types';
import { Link } from '../../book/links';
import { OopsAcorn } from '../../ui/OopsAcorn';
import { Confirm } from './Confirm';
import * as C from './copy';
import { asks, tag, type Answers, type Row } from './logic';

type Props = {
  row: Row; account: Account | null; accounts: Account[]; parent: boolean;
  onAccount: (value: string) => void; onAnswers: (a: Answers) => void; onUse: (el: HTMLElement | null) => void;
  onRemove: (el: HTMLElement | null) => void;
};

/** One file in the batch: its name, its tag (words, never colour alone), its account and ×. A new layout's row opens
 *  into the confirm (P12). */
export function FileRow({ row, account, accounts, parent, onAccount, onAnswers, onUse, onRemove }: Props) {
  const li = useRef<HTMLLIElement>(null);
  const box = useRef<HTMLDivElement>(null);
  const groups = useMemo(() => {
    const m = new Map<string, Account[]>();
    for (const a of accounts) m.set(a.institution, [...(m.get(a.institution) ?? []), a]);
    return [...m.entries()];
  }, [accounts]);
  const warn = row.status === 'error';
  const open = row.status === 'ready' && asks(row, account) && !row.confirmed;
  return (
    <li ref={li} className="imp-row" aria-busy={row.status === 'reading' || undefined}>
      <div className="imp-row__line">
        <span className="imp-row__name">{row.name}</span>
        {warn && <OopsAcorn />}
        <span className={`imp-row__tag${warn ? ' imp-row__tag--warn' : ''}`}>{tag(row, account)}</span>
        {row.status === 'ready' && (
          <select className="imp-row__account" aria-label={C.ACCOUNT_FOR.replace('{file}', row.name)} value={row.accountId ?? ''}
            onChange={(e) => onAccount(e.target.value)}>
            <option value="">{C.ACCOUNT_EMPTY}</option>
            {groups.map(([inst, list]) => (
              <optgroup key={inst} label={inst}>{list.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}</optgroup>
            ))}
            {!parent && <option value="new">{C.NEW_ACCOUNT}</option>}
          </select>
        )}
        <button type="button" className="icon-btn imp-row__remove" aria-label={C.REMOVE.replace('{file}', row.name)}
          onClick={() => onRemove(li.current)}><X size={20} aria-hidden="true" /></button>
      </div>
      {parent && row.status === 'ready' && row.accountId === null && <Link className="small" to="/inventory">{C.IN_INVENTORY}</Link>}
      {open && <div ref={box}><Confirm row={row} account={account} onChange={onAnswers} onUse={() => onUse(box.current)} /></div>}
    </li>
  );
}
