import { useQuery } from '@tanstack/react-query';
import { api } from '../../api/client';
import { Link } from '../../book/links';
import { localYmd } from '../../lib/format';

export type CameFromOut = {
  kind: 'simplefin' | 'file' | 'statement' | 'typed'; label: string | null; at: string | null;
  batch_id?: number; by?: string | null; count?: number; undoable?: boolean;
  period?: { start: string; end: string } | null; page?: number | null; check?: 'adds_up' | 'anyway' | null; gap_cents?: number | null;
};
// Plan-owned copy from JR's examples (Oct 31): "SimpleFIN · Chase · synced Oct 12", "Chase-checking-2024.csv ·
// imported Oct 31 by JR", "Typed in".
const C = { simplefin: 'SimpleFIN · {institution}', synced: ' · synced {date}', file: '{file} · imported {date}', by: ' by {name}',
  typed: 'Typed in', showAll: 'Show all {n} from this file',
  statement: 'Statement, {month} (PDF)', page: ', page {n}', imported: ' · imported {date}', addedUp: ' · added up ✓',
  didnt: " · didn't add up by {gap}", didntNoGap: " · didn't add up" };   // no gap: a balance the scan didn't read
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const day = (iso: string) => { const [, m, d] = localYmd(iso).split('-').map(Number); return `${MONTHS[m - 1]} ${d}`; };

export function cameFromLine(c: CameFromOut): string {
  if (c.kind === 'simplefin') return C.simplefin.replace('{institution}', c.label ?? '') + (c.at ? C.synced.replace('{date}', day(c.at)) : '');
  if (c.kind === 'statement') {
    const [y, m] = (c.period?.end ?? c.at!.slice(0, 10)).split('-').map(Number);
    const head = C.statement.replace('{month}', `${MONTHS[m - 1]} ${y}`) + (c.page ? C.page.replace('{n}', String(c.page)) : '');
    const check = c.check === 'anyway' && !c.gap_cents ? C.didntNoGap
      : c.check === 'anyway' ? C.didnt.replace('{gap}', '$' + (Math.abs(c.gap_cents ?? 0) / 100).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }))
      : C.addedUp;
    return head + C.imported.replace('{date}', day(c.at!)) + check;
  }
  if (c.kind === 'file') return C.file.replace('{file}', c.label ?? '').replace('{date}', day(c.at!)) + (c.by ? C.by.replace('{name}', c.by) : '');
  return C.typed;
}

/** Came from (JR, Oct 31): one quiet line in the transaction detail, its own lazy chunk, loaded when the detail opens
 *  (plan Engineering choice 2). A file's line opens all its rows, where its Undo is. */
export default function CameFrom({ txnId }: { txnId: number }) {
  const q = useQuery({ queryKey: ['came-from', txnId], retry: false,
    queryFn: () => api<{ came_from: CameFromOut }>(`/api/transactions/${txnId}/came-from`) });
  const c = q.data?.came_from;
  if (!c) return null;
  return (
    <p className="came-from small muted" data-testid="came-from">
      {cameFromLine(c)}
      {(c.kind === 'file' || c.kind === 'statement') && c.batch_id && c.count ? (
        <> · <Link to={`/transactions?batch=${c.batch_id}&dates=all`}>{C.showAll.replace('{n}', c.count.toLocaleString('en-US'))}</Link></>
      ) : null}
    </p>
  );
}
