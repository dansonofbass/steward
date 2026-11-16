import { money, type MoneyOpts } from '../lib/format';
import './Money.css';

type Props = { cents: number; sign?: MoneyOpts['sign']; compact?: boolean; size?: 's' | 'm' | 'l' | 'xl' };

export function Money({ cents, sign, compact, size = 'm' }: Props) {
  const dir = cents > 0 ? ' money--in' : cents < 0 ? ' money--out' : '';
  return <span className={`money money--${size}${dir}`}>{money(cents, { sign, compact })}</span>;
}
