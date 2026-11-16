// Typed amounts to whole units without floating point: "3.25" -> 325, "12000" -> 1200000, "-0.5" -> -50.
// The same shape serves dollars to cents and percent to basis points (both are hundredths).
export const TWO_DECIMALS = 'Use at most two decimals.';
export const NOT_A_NUMBER = 'Enter a number like 1250.00.';

export type Parsed = { value: number } | { error: string };

export function toHundredths(input: string): Parsed {
  const text = input.trim().replace(/^(-?)\$/, '$1').replace(/,/g, '');
  const m = /^(-?)(\d+)(?:\.(\d*))?$/.exec(text);
  if (!m) return { error: NOT_A_NUMBER };
  const [, sign, whole, frac = ''] = m;
  if (frac.length > 2) return { error: TWO_DECIMALS };
  const n = Number(whole) * 100 + Number(frac.padEnd(2, '0'));
  if (!Number.isSafeInteger(n)) return { error: NOT_A_NUMBER };
  return { value: sign ? -n : n };
}

/** 325 -> "3.25", 300 -> "3", 320 -> "3.2", 125000 -> "1250" for display in a text field. */
export function fromHundredths(n: number): string {
  const sign = n < 0 ? '-' : '';
  const abs = Math.abs(n);
  const whole = Math.trunc(abs / 100);
  const frac = String(abs % 100).padStart(2, '0').replace(/0+$/, '');
  return `${sign}${whole}${frac ? `.${frac}` : ''}`;
}

/**
 * Format what someone is typing as a dollar amount: "1492733" -> "1,492,733", "$1,234.56" -> "1,234.56".
 * Drops anything that is not a digit, one decimal point, or (when allowed) a leading minus.
 * Decimals are kept as typed so toHundredths can still say "at most two decimals".
 */
export function formatMoneyInput(raw: string, allowNegative = false): string {
  const negative = allowNegative && /^\s*(?:\$?\s*-|\(\s*\$?)/.test(raw); // "-5" or an accounting "(5)"
  const body = raw.replace(/[^\d.]/g, '');
  const dot = body.indexOf('.');
  const whole = (dot < 0 ? body : body.slice(0, dot)).replace(/^0+(?=\d)/, '');
  const frac = dot < 0 ? null : body.slice(dot + 1).replace(/\./g, '');
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  const text = frac === null ? grouped : `${grouped || '0'}.${frac}`;
  if (text === '') return negative ? '-' : '';
  return negative ? `-${text}` : text;
}

/** How many digits, points and minus signs sit before `pos`; used to put the caret back after reformatting. */
export function significantBefore(text: string, pos: number): number {
  return text.slice(0, pos).replace(/[^\d.-]/g, '').length;
}

/** The caret position in `text` that has `count` significant characters before it. */
export function caretAfter(text: string, count: number): number {
  let seen = 0;
  for (let i = 0; i < text.length; i++) {
    if (seen === count) return i;
    if (/[\d.-]/.test(text[i])) seen++;
  }
  return text.length;
}

/** Cents as the text a money field starts with: 149273300 -> "1,492,733". */
export const dollarsText = (cents: number): string => formatMoneyInput(fromHundredths(cents), true);
