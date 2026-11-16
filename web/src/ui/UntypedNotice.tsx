import { TriangleAlert } from 'lucide-react';
import { useCanEdit } from '../book/BookContext';
import { Link } from '../book/links';
import type { Account } from '../api/types';
import { Notice } from './Notice';
import './UntypedNotice.css';

export type UntypedWhere = 'spending' | 'plan';

/** New accounts from the bank start as `unknown` and are left out of spending, surplus and cash flow until typed. */
export function untypedCount(accounts: Account[] | undefined): number {
  return (accounts ?? []).filter((a) => a.is_active && a.type === 'unknown').length;
}

export function untypedCopy(n: number, where: UntypedWhere): { eyebrow: string; body: string; link: string } {
  const one = n === 1;
  const link = one ? 'Set the type of 1 new account' : `Set the type of ${n} new accounts`;
  const eyebrow = 'Accounts without a type';
  if (where === 'spending') {
    return {
      eyebrow,
      body: one ? '1 new account has no type. It is not included here or in the plan.' : `${n} new accounts have no type. They are not included here or in the plan.`,
      link,
    };
  }
  return {
    eyebrow,
    body: one
      ? '1 new account has no type. Until it has one, it is not included in spending or savings, and the plan is less accurate.'
      : `${n} new accounts have no type. Until they have one, they are not included in spending or savings, and the plan is less accurate.`,
    link,
  };
}

export function UntypedNotice({ accounts, where }: { accounts: Account[] | undefined; where: UntypedWhere }) {
  const n = untypedCount(accounts);
  const canEdit = useCanEdit();   // Banks, where a type is set, is a manager's
  if (n === 0) return null;
  const c = untypedCopy(n, where);
  return (
    <Notice tone="warn">
      <div className="notice__row">
        <TriangleAlert className="notice__icon" size={20} aria-hidden="true" />
        <div className="notice__body">
          <span className="eyebrow">{c.eyebrow}</span>
          <span>{c.body}</span>
          {canEdit && <Link className="link" to="/settings/banks">{c.link}</Link>}
        </div>
      </div>
    </Notice>
  );
}
