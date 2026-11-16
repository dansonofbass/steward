import { LIST_DISPLAY } from '../lib/copy';
import './TxnName.css';

type Named = { nickname?: string | null; merchant: string | null; raw_description: string };

/** The payee a row shows: its merchant, a caller's word (Transfer), or the bank's text. */
export const payeeOf = (t: Named, fallback?: string): string => t.merchant || fallback || t.raw_description;
/** "Disney+ (PayPal)" as plain text, for a title or a label (polish round P5). */
export const txnLabel = (t: Named, fallback?: string): string =>
  (t.nickname ? LIST_DISPLAY.replace('{name}', t.nickname).replace('{payee}', payeeOf(t, fallback)) : payeeOf(t, fallback));

/** A row's name in a list: its name with the payee muted after it, or the payee alone. Sorting and grouping still use
 *  the merchant. */
export function TxnName({ t, fallback }: { t: Named; fallback?: string }) {
  if (!t.nickname) return <>{payeeOf(t, fallback)}</>;
  return <>{t.nickname} <span className="txn-name__payee">({payeeOf(t, fallback)})</span></>;
}
