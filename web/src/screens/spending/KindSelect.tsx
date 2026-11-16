import type { SpendingKind } from '../../api/types';
import * as C from './copy';
import { fill } from './format';

const ORDER: SpendingKind[] = ['fixed', 'commitment', 'everyday', 'occasional'];

/** A category's kind (spec, Kinds): Bill · Commitment · Flexible · Once in a while, labelled "Kind of {label}". */
export function KindSelect({ label, value, onChange, disabled = false, className = 'sp-trow__kind' }:
{ label: string; value: SpendingKind; onChange: (k: SpendingKind) => void; disabled?: boolean; className?: string }) {
  return (
    <select className={className} aria-label={fill(C.KIND_OF, { label })} value={value} disabled={disabled}
      onChange={(e) => onChange(e.target.value as SpendingKind)}>
      {ORDER.map((k) => <option key={k} value={k}>{C.KIND_NAME[k]}</option>)}
    </select>
  );
}
