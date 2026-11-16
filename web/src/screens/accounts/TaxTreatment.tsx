import { TriangleAlert } from 'lucide-react';
import type { Account } from '../../api/types';
import { useCanEdit } from '../../book/BookContext';
import { Link } from '../../book/links';
import {
  TREAT_COUNTED, TREAT_NEW_MANY, TREAT_NEW_ONE, TREAT_NOT_COUNTED, TREAT_SET_ITS_TYPE, TREAT_SET_THEIR_TYPE, TREAT_TITLE,
} from '../../lib/copy';
import { dollars } from '../../lib/format';
import { treatment } from './treatment';

/** Accounts by how the plan treats them (plan subpages decision 6: moved from the Plan as it was). */
export function TaxTreatment({ accounts }: { accounts: Account[] }) {
  const t = treatment(accounts);
  const canEdit = useCanEdit();   // Banks, where a type is set, is a manager's
  return (
    <section className="acct-sec" aria-labelledby="tax-h">
      <h2 id="tax-h">{TREAT_TITLE}</h2>
      <div className="card treat">
        {t.counted.map((r) => (
          <div key={r.key} className="treat__row"><span className="treat__name">{r.name}</span><span className="money money--m">{dollars(r.cents)}</span><span className="treat__sub">{r.sub}</span></div>
        ))}
        <div className="treat__total"><span>{TREAT_COUNTED}</span><span className="money">{dollars(t.total)}</span></div>
        {t.outside.map((r) => (
          <div key={r.key} className="treat__row is-outside"><span className="treat__name">{r.name}</span><span className="money money--m">{dollars(r.cents)}</span><span className="treat__sub">{r.sub}</span></div>
        ))}
        {t.untyped.n > 0 && (
          <div className="treat__row is-outside">
            <span className="treat__name"><TriangleAlert className="i warn" size={20} aria-hidden="true" />{t.untyped.n === 1 ? TREAT_NEW_ONE : TREAT_NEW_MANY.replace('{n}', String(t.untyped.n))}</span>
            <span className="money money--m">{dollars(t.untyped.cents)}</span>
            <span className="treat__sub">{TREAT_NOT_COUNTED}{canEdit && <> · <Link to="/settings/banks">{t.untyped.n === 1 ? TREAT_SET_ITS_TYPE : TREAT_SET_THEIR_TYPE}</Link></>}</span>
          </div>
        )}
      </div>
    </section>
  );
}
