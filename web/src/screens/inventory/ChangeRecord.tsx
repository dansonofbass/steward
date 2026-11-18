import { ChevronDown, History } from 'lucide-react';
import { useRef, useState } from 'react';
import { useBook } from '../../book/BookContext';
import { TRY_AGAIN } from '../../lib/copy';
import { Button } from '../../ui/Button';
import { Card } from '../../ui/Card';
import { Notice } from '../../ui/Notice';
import { Skeleton } from '../../ui/Skeleton';
import { useChanges, type ChangeRow } from './api';
import { ChangeDetails, ChangeText } from './ChangeLine';
import * as C from './copy';
import { fill } from './format';
import { CHANGE_ICONS } from './marks';
import './inventory.css';
import { clockTime, dayOf } from '../../lib/today';

// The household's day and clock (issue #26): a group, its heading and each row's time all agree near midnight,
// wherever the device is. The heading is read from the day itself (a YYYY-MM-DD, formatted as that date in UTC). A
// row whose time can't be read has no day (''), and gets a blank heading rather than a RangeError from Intl.
const DAY = new Intl.DateTimeFormat('en-US', { timeZone: 'UTC', weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' });
const dayLabel = (ymd: string) => (ymd ? DAY.format(Date.parse(ymd)) : '');

/** Settings → Change record (spec 5; decision 8). Read-only for everyone. */
export function ChangeRecord() {
  const book = useBook();
  const [who, setWho] = useState('');
  const [kind, setKind] = useState('');
  const q = useChanges({ user_id: who || undefined, kind: kind || undefined });
  const rows: ChangeRow[] = q.data?.pages.flatMap((p) => p.changes) ?? [];
  // Keep the last list of people, so the choices don't vanish while a filtered list loads.
  const loaded = q.data?.pages[0]?.people;
  const known = useRef<{ id: number; name: string }[]>([]);
  if (loaded) known.current = loaded;
  const people = known.current;
  const groups: { key: string; label: string; rows: ChangeRow[] }[] = [];
  for (const r of rows) {
    const key = dayOf(r.at);
    if (groups.length && groups[groups.length - 1].key === key) groups[groups.length - 1].rows.push(r);
    else groups.push({ key, label: dayLabel(key), rows: [r] });
  }
  return (
    <section className="stack" aria-label={C.CHANGE_RECORD}>
      <div className="page-head">
        <h2 className="subhead"><History size={20} aria-hidden="true" /> {C.CHANGE_RECORD}</h2>
        <p className="muted">{fill(C.CHANGES_LEDE, { book: book?.name ?? '' })}</p>
      </div>
      <div className="grid-2">
        <div className="field select">
          <label className="field__label" htmlFor="chg-who">{C.PERSON}</label>
          <select id="chg-who" value={who} onChange={(e) => setWho(e.target.value)}>
            <option value="">{C.EVERYONE}</option>
            {people.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
          <ChevronDown size={20} aria-hidden="true" />
        </div>
        <div className="field select">
          <label className="field__label" htmlFor="chg-kind">{C.KIND_OF_CHANGE}</label>
          <select id="chg-kind" value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="">{C.ALL_CHANGES}</option>
            {C.KIND_FILTERS.map(([k, label]) => <option key={k} value={k}>{label}</option>)}
          </select>
          <ChevronDown size={20} aria-hidden="true" />
        </div>
      </div>
      {q.isPending && <Card><Skeleton lines={5} /></Card>}
      {q.isError && <Notice tone="error"><p>{q.error.message}</p><Button variant="quiet" onClick={() => q.refetch()}>{TRY_AGAIN}</Button></Notice>}
      {q.isSuccess && rows.length === 0 && <p className="muted">{C.NO_CHANGES_YET}</p>}
      {groups.length > 0 && (
        <div className="card chg">
          {groups.map(({ key, label, rows: list }) => (
            <div key={key}>
              <div className="chg__day">{label}</div>
              {list.map((r) => {
                const Icon = CHANGE_ICONS[r.icon] ?? CHANGE_ICONS.pencil;
                return (
                  <div key={r.id} className="chg__row">
                    <Icon size={20} aria-hidden="true" />
                    <div className="chg__what">
                      <div className="chg__line"><ChangeText row={r} /><span className="chg__time">{clockTime(r.at)}</span></div>
                      <ChangeDetails row={r} />
                    </div>
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      )}
      {q.hasNextPage && <div className="row-actions"><Button variant="quiet" busy={q.isFetchingNextPage} onClick={() => void q.fetchNextPage()}>{C.SHOW_OLDER}</Button></div>}
      <p className="small muted">{C.CHANGES_FOOT}</p>
    </section>
  );
}

export default ChangeRecord;
