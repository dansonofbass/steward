import { ArrowLeftRight, Briefcase, MessageSquare } from 'lucide-react';
import type { MouseEvent, ReactNode } from 'react';
import type { Txn } from '../../api/types';
import { label } from '../../lib/categories';
import { BUSINESS, BUSINESS_PCT, NOTE_MARK, NOTE_MARK_ONE, SHOW_MORE, TRANSFER } from '../../lib/copy';
import { dateLabel } from '../../lib/format';
import { useLongPress } from '../../lib/selection';
import { Button } from '../../ui/Button';
import { Money } from '../../ui/Money';
import { Skeleton } from '../../ui/Skeleton';
import { TxnName } from '../../ui/TxnName';

type Props = {
  rows: Txn[];
  loading: boolean;
  hasMore: boolean;
  loadingMore: boolean;
  onMore: () => void;
  selectedId: number | null;
  onSelect: (t: Txn) => void;
  empty: ReactNode;
  today: Date;
  /** Bulk sort: selection mode is on, so a click picks the row (Shift: a range) instead of opening it. */
  selecting?: boolean;
  picked?: ReadonlySet<number>;
  onPick?: (id: number, range: boolean) => void;
  /** A long press on a phone starts a selection with that row picked. */
  onLongPress?: ((id: number) => void) | null;
};

function groupByDay(rows: Txn[]): [string, Txn[]][] {
  const groups: [string, Txn[]][] = [];
  for (const t of rows) {
    const last = groups[groups.length - 1];
    if (last && last[0] === t.posted_at) last[1].push(t);
    else groups.push([t.posted_at, [t]]);
  }
  return groups;
}

export function TxnList({ rows, loading, hasMore, loadingMore, onMore, selectedId, onSelect, empty, today, selecting = false, picked, onPick, onLongPress = null }: Props) {
  const press = useLongPress(selecting ? null : onLongPress);
  if (loading) {
    return (
      <div aria-busy="true" aria-label="Loading transactions">
        {[0, 1, 2, 3, 4, 5].map((i) => <div className="txn txn--skeleton" key={i}><Skeleton lines={2} /></div>)}
      </div>
    );
  }
  if (rows.length === 0) return <>{empty}</>;
  return (
    <div {...press}>
      {groupByDay(rows).map(([day, items]) => (
        <section className="day" key={day} data-date={day}>
          <h3 className="day__head eyebrow">{dateLabel(day, today)}</h3>
          {items.map((t) => {
            const transfer = t.is_transfer || t.category === 'transfer';
            const raw = !t.merchant && !transfer;
            const on = picked?.has(t.id) ?? false;
            const state = selecting
              ? { role: 'checkbox', 'aria-checked': on, onClick: (e: MouseEvent) => { onPick?.(t.id, e.shiftKey); } }
              : { 'aria-pressed': selectedId === t.id, onClick: () => onSelect(t) };
            return (
              <button type="button" key={t.id} data-testid="txn-row" data-id={t.id} {...state}
                className={`txn${selecting ? ` is-picking${on ? ' is-picked' : ''}` : selectedId === t.id ? ' is-selected' : ''}`}>
                {selecting && <span className={`pick-box${on ? ' is-on' : ''}`} aria-hidden="true" />}
                <span className={`txn__name${raw && !t.nickname ? ' is-raw' : ''}`}><TxnName t={t} fallback={transfer ? TRANSFER : undefined} /></span>
                <Money cents={t.amount_cents} sign="auto" />
                <span className="txn__meta">
                  <span>{t.account_name} ·</span>
                  {transfer ? <span className="txn__transfer"><ArrowLeftRight size={20} aria-hidden="true" />{TRANSFER}</span> : <span>{label(t.category)}</span>}
                </span>
                {t.business_pct > 0 && <span className="tag txn__tag"><Briefcase size={20} aria-hidden="true" />{t.business_pct === 100 ? BUSINESS : BUSINESS_PCT.replace('{pct}', String(t.business_pct))}</span>}
                {(t.note_count ?? 0) > 0 && <span className="tag txn__note"><MessageSquare size={20} aria-hidden="true" />{t.note_count === 1 ? NOTE_MARK_ONE : NOTE_MARK.replace('{n}', String(t.note_count))}</span>}
              </button>
            );
          })}
        </section>
      ))}
      {hasMore && (
        <div className="txn-more">
          <Button variant="quiet" busy={loadingMore} onClick={onMore}>{SHOW_MORE}</Button>
        </div>
      )}
    </div>
  );
}
