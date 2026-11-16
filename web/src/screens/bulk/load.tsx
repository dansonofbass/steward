import { type ComponentProps, type ComponentType } from 'react';
import { lazyScreen } from '../../lib/lazyScreen';
import { BULK_UNAVAILABLE } from '../../lib/copy';
import { Notice } from '../../ui/Notice';
import type BulkSortView from './BulkSort';

type Props = ComponentProps<typeof BulkSortView>;

/** The bar's chunk couldn't be fetched (a deploy replaced it while the page was open): while selecting, one line says so
 *  where the bar would be, instead of nothing. */
function Missing({ selecting }: Props) {
  return selecting ? <div className="bulk-missing"><Notice tone="error">{BULK_UNAVAILABLE}</Notice></div> : null;
}

export const loadBulkSort = (load: () => Promise<{ default: ComponentType<Props> }> = () => import('./BulkSort')) =>
  load().catch(() => ({ default: Missing }));
/** Bulk sort's bar and result line, loaded at the first Select (Transactions and Review). */
export const BulkSort = lazyScreen(() => loadBulkSort());
