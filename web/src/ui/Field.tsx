import { cloneElement, useId, useLayoutEffect, useRef, type ReactElement, type ReactNode } from 'react';
import { focusFirstInvalid, watchSubmits } from '../lib/formErrors';
import { useLive } from './Live';
import { Notice } from './Notice';
import './Field.css';

type Props = {
  label: string;
  hint?: string;
  error?: ReactNode;
  /** Show the error as an inline Notice (sign-in) instead of small text. */
  notice?: boolean;
  children: ReactElement<Record<string, unknown>>;
};

/** A labelled control. Its error is tied to it (aria-describedby and aria-invalid), so focus on the control reads the
 *  error too (WEB-4). When the error comes from a submit, focus goes to the form's first invalid field; when it comes
 *  any other way (a check as you leave the field, an autosave that failed), the error is said politely once. */
export function Field({ label, hint, error, notice = false, children }: Props) {
  const id = useId();
  const hintId = `${id}-hint`;
  const errId = `${id}-err`;
  const describedBy = [hint ? hintId : '', error ? errId : ''].filter(Boolean).join(' ') || undefined;
  const live = useLive();
  const said = useRef<string | null>(null);
  useLayoutEffect(() => {
    watchSubmits();
    const text = error ? document.getElementById(errId)?.textContent ?? '' : '';
    const was = said.current;
    said.current = text;
    if (!text || text === was) return;
    if (focusFirstInvalid(document.getElementById(id)?.closest('form'))) return;
    if (was !== null) live?.say(`${label}: ${text}`);   // not for an error the field opens with
  });
  return (
    <div className={`field${error ? ' field--error' : ''}`}>
      <label htmlFor={id} className="field__label">{label}</label>
      {cloneElement(children, { id, 'aria-describedby': describedBy, 'aria-invalid': error ? true : undefined })}
      {hint && <p id={hintId} className="field__hint">{hint}</p>}
      {error && (notice
        ? <div id={errId}><Notice tone="error">{error}</Notice></div>
        : <p id={errId} className="field__error">{error}</p>)}
    </div>
  );
}

/** An error about the whole form, or one that names no single field (the server refused, a figure didn't parse): an
 *  alert, which a screen reader reads when it appears. A field's own error goes in its Field. */
export function FormError({ children }: { children: ReactNode }) {
  return <p className="field__error" role="alert">{children}</p>;
}
