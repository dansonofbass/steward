import { LoaderCircle, type LucideIcon } from 'lucide-react';
import { useEffect, useState, type ButtonHTMLAttributes, type MouseEvent, type Ref } from 'react';
import './Button.css';

type Props = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'quiet' | 'danger';
  busy?: boolean;
  icon?: LucideIcon;
  ref?: Ref<HTMLButtonElement>;
};

const SPINNER_DELAY_MS = 100;

// A busy submit button must not submit its form again.
function blockWhileBusy(e: MouseEvent<HTMLButtonElement>) {
  e.preventDefault();
  e.stopPropagation();
}

export function Button({ variant = 'primary', busy = false, icon: Icon, className, children, disabled, type = 'button', onClick, ...rest }: Props) {
  const [spinning, setSpinning] = useState(false);
  useEffect(() => {
    if (!busy) {
      setSpinning(false);
      return;
    }
    const t = setTimeout(() => setSpinning(true), SPINNER_DELAY_MS);
    return () => clearTimeout(t);
  }, [busy]);

  const cls = ['btn', `btn--${variant}`, spinning ? 'btn--spinning' : '', className].filter(Boolean).join(' ');
  return (
    <button {...rest} type={type} className={cls} disabled={disabled} aria-busy={busy || undefined} aria-disabled={busy || undefined} onClick={busy ? undefined : onClick} onClickCapture={busy ? blockWhileBusy : undefined}>
      <span className="btn__content">
        {Icon && <Icon size={20} aria-hidden="true" />}
        <span>{children}</span>
      </span>
      {spinning && <LoaderCircle className="btn__spinner" size={20} aria-hidden="true" />}
    </button>
  );
}
