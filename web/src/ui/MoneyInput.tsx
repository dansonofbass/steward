import { useLayoutEffect, useRef, type ChangeEvent, type InputHTMLAttributes } from 'react';
import { caretAfter, formatMoneyInput, significantBefore } from '../screens/settings/money';
import { Affix } from './Affix';

type Props = Omit<InputHTMLAttributes<HTMLInputElement>, 'value' | 'onChange' | 'type'> & {
  value: string;
  onValueChange: (text: string) => void;
  allowNegative?: boolean;
  /** Text after the amount, such as "a year". */
  post?: string;
};

/**
 * A dollar field: "$" before the amount, thousands separators as you type, caret kept in place.
 * The value is the formatted text; hand it to toHundredths to get integer cents.
 */
export function MoneyInput({ value, onValueChange, allowNegative = false, post, ...input }: Props) {
  const ref = useRef<HTMLInputElement>(null);
  const caret = useRef<number | null>(null);

  useLayoutEffect(() => {
    const el = ref.current;
    if (el && caret.current !== null && document.activeElement === el) el.setSelectionRange(caret.current, caret.current);
    caret.current = null;
  });

  function change(e: ChangeEvent<HTMLInputElement>) {
    const raw = e.target.value;
    const next = formatMoneyInput(raw, allowNegative);
    caret.current = caretAfter(next, significantBefore(raw, e.target.selectionStart ?? raw.length));
    onValueChange(next);
  }

  return <Affix {...input} pre="$" post={post} inputMode="decimal" inputRef={ref} value={value} onChange={change} />;
}
