import { ChevronRight, FileUp, Landmark, Pencil, type LucideIcon } from 'lucide-react';
import { useState } from 'react';
import { Link } from '../../book/links';
import {
  ADD_ACCOUNT, ADD_AN_ACCOUNT, IMPORT_A_FILE, IMPORT_A_FILE_HINT, LINK_A_BANK, LINK_A_BANK_HINT, ONE_YOU_UPDATE_MANUALLY, ONE_YOU_UPDATE_MANUALLY_HINT,
} from '../../lib/copy';
import { Sheet } from '../../ui/Sheet';
import { AddAccountForm } from './ManualAccounts';
import './accounts.css';

function Way({ icon: Icon, name, hint }: { icon: LucideIcon; name: string; hint: string }) {
  return (
    <>
      <Icon size={24} aria-hidden="true" />
      <span className="way__name">{name}</span>
      <span className="way__sub">{hint}</span>
      <ChevronRight size={20} aria-hidden="true" />
    </>
  );
}

/** The Accounts tab's three ways in (decision 6). A bank and a file are set up in Settings, which keeps the plumbing;
 *  an account updated manually is added here, the same form Banks and accounts uses. The form swaps in inside the
 *  same sheet, so focus moves to its first field and, on close, goes back to Add an account. */
export function AddAccount({ onClose }: { onClose: () => void }) {
  const [manual, setManual] = useState(false);
  return (
    <Sheet open onClose={onClose} title={manual ? ADD_ACCOUNT : ADD_AN_ACCOUNT}>
      {manual ? <AddAccountForm onSaved={onClose} autoFocus /> : (
        <div className="card ways">
          <Link className="way" to="/settings/banks" onClick={onClose}><Way icon={Landmark} name={LINK_A_BANK} hint={LINK_A_BANK_HINT} /></Link>
          <button className="way" type="button" onClick={() => setManual(true)}>
            <Way icon={Pencil} name={ONE_YOU_UPDATE_MANUALLY} hint={ONE_YOU_UPDATE_MANUALLY_HINT} />
          </button>
          <Link className="way" to="/settings/import" onClick={onClose}><Way icon={FileUp} name={IMPORT_A_FILE} hint={IMPORT_A_FILE_HINT} /></Link>
        </div>
      )}
    </Sheet>
  );
}
