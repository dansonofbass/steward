import type { LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';
import { CANCEL } from '../lib/copy';
import { Button } from './Button';
import { Notice } from './Notice';
import { Sheet } from './Sheet';
import './ConfirmSheet.css';

type Props = {
  open: boolean;
  /** A question that names what is acted on: "Remove Vee from Mom?" */
  title: string;
  /** What happens and what stays, in one or two plain sentences. */
  body?: ReactNode;
  /** Anything else the sheet should show between the body and the buttons (a rule's wording, a note field). */
  children?: ReactNode;
  /** The confirm button's label; the action word again, or the action with its target ("Remove me from Mom"). */
  action: string;
  icon?: LucideIcon;
  /** `danger` for anything that removes or deletes; `primary` for a change of access that removes nothing. */
  variant?: 'danger' | 'primary';
  busy?: boolean;
  error?: string | null;
  /** The way out, "Cancel" unless the action itself is a cancel ("Keep it"). */
  cancel?: string;
  onConfirm: () => void;
  onClose: () => void;
  /** Where focus goes when it closes. Required (THO-1): after a removal the button that opened the sheet is gone, and
   *  focus would fall to the page body. Pass a useRemoval's returnTo, or BACK_TO_OPENER when the opener stays. */
  returnTo: () => HTMLElement | null;
};

/** The one confirmation for every destructive or access-changing action: a Sheet that says exactly what happens and what stays, then asks for a second click. */
export function ConfirmSheet({ open, title, body, children, action, icon, variant = 'danger', busy = false, error, cancel = CANCEL, onConfirm, onClose, returnTo }: Props) {
  return (
    <Sheet open={open} onClose={onClose} title={title} returnTo={returnTo}>
      <div className="confirm-sheet">
        {body && <p>{body}</p>}
        {children}
        {error && <Notice tone="error">{error}</Notice>}
        <div className="confirm-sheet__acts">
          <Button variant={variant} icon={icon} busy={busy} onClick={onConfirm}>{action}</Button>
          <Button variant="quiet" onClick={onClose}>{cancel}</Button>
        </div>
      </div>
    </Sheet>
  );
}
