import { ChevronLeft, ChevronRight } from 'lucide-react';
import { useState } from 'react';
import { useBusinessLine } from '../../api/hooks';
import type { ReportLine, Txn } from '../../api/types';
import { dateLabel, money } from '../../lib/format';
import { Button } from '../../ui/Button';
import { Money } from '../../ui/Money';
import { Notice } from '../../ui/Notice';
import { Sheet } from '../../ui/Sheet';
import { Skeleton } from '../../ui/Skeleton';
import { TxnDetail } from '../transactions/TxnDetail';
import { BACK, NO_ROWS, SHARE_OF } from './copy';

type Props = { year: number; line: ReportLine | null; onClose: () => void };

/** Spec 5: every line opens its transactions. A row opens the same detail as Transactions, to retag it here. */
export function LineSheet({ year, line, onClose }: Props) {
  const q = useBusinessLine(year, line?.key ?? null);
  const [picked, setPicked] = useState<Txn | null>(null);
  const today = new Date();
  const close = () => { setPicked(null); onClose(); };
  return (
    <Sheet open={line !== null} onClose={close} title={picked ? picked.merchant || picked.raw_description : line?.label ?? ''}>
      {picked ? (
        <div className="stack">
          <Button variant="quiet" icon={ChevronLeft} onClick={() => setPicked(null)}>{BACK}</Button>
          <TxnDetail txn={picked} today={today} showHeader={false} onClose={() => setPicked(null)} onSaved={(t) => setPicked(t)} />
        </div>
      ) : q.isError ? <Notice tone="error">{q.error.message}</Notice>
        : !q.data ? <Skeleton lines={4} />
        : q.data.transactions.length === 0 ? <p className="muted">{NO_ROWS}</p>
        : (
          <ul className="biz-rows">
            {q.data.transactions.map((t) => (
              <li key={t.id}>
                <button type="button" className="biz-row" onClick={() => setPicked(t)}>
                  <span className="biz-row__name">{t.merchant || t.raw_description}</span>
                  <Money cents={t.share_cents} />
                  <span className="small muted">{dateLabel(t.posted_at, today)} · {t.account_name}</span>
                  {t.business_pct < 100 && <span className="small muted">{SHARE_OF.replace('{share}', money(Math.abs(t.share_cents))).replace('{amount}', money(Math.abs(t.amount_cents)))}</span>}
                  <ChevronRight className="biz-row__go" size={20} aria-hidden="true" />
                </button>
              </li>
            ))}
          </ul>
        )}
    </Sheet>
  );
}
