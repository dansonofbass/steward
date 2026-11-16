import { ChevronLeft, Search } from 'lucide-react';
import { Suspense, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';
import { useAccounts, useTransactions, type TxnParams } from '../api/hooks';
import type { SortManyReply, Txn } from '../api/types';
import { useCanEdit, useIsHousehold } from '../book/BookContext';
import { Link } from '../book/links';
import {
  ACCOUNTS, ALL_TRANSACTIONS, INVENTORY, NOTHING_LAST_7, NOTHING_MATCHED, NOTHING_MATCHED_BODY, SEARCH, SEARCH_HINT, SELECT, SHOW_LAST_30, TRY_AGAIN,
} from '../lib/copy';
import { useSelection } from '../lib/selection';
import { useWide } from '../lib/useWide';
import { Button } from '../ui/Button';
import { Card } from '../ui/Card';
import { EmptyState } from '../ui/EmptyState';
import { Field } from '../ui/Field';
import { Notice } from '../ui/Notice';
import { Sheet } from '../ui/Sheet';
import { txnLabel } from '../ui/TxnName';
import { withParam } from './transactions/params';
import { parseMode, rangeFor, type DatesMode } from './transactions/dates';
import { Filters, type FilterKey } from './transactions/Filters';
import { TxnDetail } from './transactions/TxnDetail';
import { TxnList } from './transactions/TxnList';
import './transactions.css';
import { BulkSort } from './bulk/load';
import { lazyScreen } from '../lib/lazyScreen';

const BatchBar = lazyScreen(() => import('./transactions/BatchBar'));

/** What a bulk sort or its Undo moves, as a single sort's detail refreshes it. */
const BULK_REFRESH = ['transactions', 'review', 'business', 'spending', 'plan', 'matching', 'reimburse'];

/** All transactions, or with `accountId` one account's: that account is fixed (no Account chip, nothing in the
 *  address) and `head`, the account page's own back link and title, stands in for All transactions' (engineering choice 2). */
export default function Transactions({ accountId, head }: { accountId?: number; head?: ReactNode }) {
  const household = useIsHousehold();
  const [sp, setSp] = useSearchParams();
  const today = useMemo(() => new Date(), []);
  const wide = useWide();
  const accounts = useAccounts();
  const [open, setOpen] = useState<FilterKey | null>(null);
  const [selected, setSelected] = useState<Txn | null>(null);

  const mode = parseMode(sp.get('dates'));
  const urlFrom = sp.get('from') ?? '';
  const urlTo = sp.get('to') ?? '';
  const range = rangeFor(mode, today, { from: urlFrom, to: urlTo });
  const q = sp.get('q') ?? '';

  function update(changes: Record<string, string | null>, replace = false) {
    setSp((prev) => {
      const next = new URLSearchParams(prev);
      for (const [k, v] of Object.entries(changes)) {
        if (v === null || v === '') next.delete(k);
        else next.set(k, v);
      }
      return next;
    }, { replace, preventScrollReset: true });   // a filter keeps the page where it is (RouteFrame resets scroll)
  }

  // The search box types freely; the URL (and so the query) follows 250 ms after the last key.
  // The timer reads the live URL so a filter chosen meanwhile is kept, and it records what it wrote
  // so a change from elsewhere (back, forward, a nav link) can tell itself apart and reach the box.
  const [text, setText] = useState(q);
  const written = useRef(q);
  useEffect(() => {
    if (text.trim() === q) return;
    const t = setTimeout(() => {
      const v = text.trim();
      written.current = v;
      setSp(withParam(window.location.search, 'q', v), { replace: true, preventScrollReset: true });
    }, 250);
    return () => clearTimeout(t);
  }, [text, q, setSp]);
  useEffect(() => {
    if (q !== written.current) { written.current = q; setText(q); }
  }, [q]);

  function setMode(m: DatesMode) {
    auto.current = false;   // the person chose: no more widening
    if (m === 'custom') {
      const r = rangeFor('7', today);
      update({ dates: 'custom', from: urlFrom || r.from!, to: urlTo || r.to! });
    } else update({ dates: m === '7' ? null : m, from: null, to: null });
  }

  const num = (k: string) => (sp.get(k) ? Number(sp.get(k)) : undefined);
  const biz = sp.get('business');
  const sortedParam = sp.get('sorted');
  const sorted = sortedParam === 'steward' || sortedParam === 'unsure' ? sortedParam : undefined;
  const params: TxnParams = {
    q: q || undefined,
    account_id: accountId ?? num('account_id'),
    category: sp.get('category') || undefined,
    owner: sp.get('owner') || undefined,
    business: biz === 'true' ? true : biz === 'false' ? false : undefined,
    sorted,
    batch: num('batch'),
    ...range,
  };
  const txns = useTransactions(params);
  const rows = txns.data?.pages.flatMap((p) => p.transactions) ?? [];

  // Bulk sort (profile spec, Sorting several rows at once): Select, then a click picks a row; the bar is its own chunk,
  // loaded at the first Select and kept for the result line.
  const canEdit = useCanEdit();
  const qc = useQueryClient();
  const order = useRef<number[]>([]);
  order.current = rows.map((t) => t.id);
  const sel = useSelection(() => order.current);
  const [bulk, setBulk] = useState(false);
  const selectBtn = useRef<HTMLButtonElement>(null);
  const startSelect = useCallback((first?: number) => { setSelected(null); setBulk(true); sel.start(first); }, [sel.start]);
  const pickedIds = sel.on ? order.current.filter((id) => sel.ids.has(id)) : [];
  const refresh = () => { for (const key of BULK_REFRESH) void qc.invalidateQueries({ queryKey: [key] }); };
  const onBulkSorted = (r: SortManyReply) => {
    if (r.skipped.length) sel.keep(r.skipped.map((s) => s.id)); else sel.end();
    if (r.sorted > 0) refresh();
  };

  // Roadmap 11: an account page never opens on an empty week. Opened with no dates and nothing else narrowing it, an
  // empty week widens to 30 days and an empty 30 days to everything, in place (no extra step back). It happens once, on
  // the way in: it stops at the first range with rows, and any range the person picks (Last 7 days too) is left alone.
  // AccountPage keys this component by account, so each account starts fresh.
  const auto = useRef(accountId !== undefined && !sp.get('dates'));
  const narrowed = Boolean(q || params.category || params.owner || params.business !== undefined || params.sorted !== undefined || params.batch !== undefined);
  const settled = txns.isSuccess && !txns.isFetching;
  useEffect(() => {
    if (!auto.current || !settled) return;
    if (rows.length > 0 || narrowed) { auto.current = false; return; }
    if (mode === '7') update({ dates: '30' }, true);
    else if (mode === '30') { auto.current = false; update({ dates: 'all' }, true); }
    else auto.current = false;
    // eslint-disable-next-line react-hooks/exhaustive-deps -- update is a fresh closure each render; the inputs are listed
  }, [settled, rows.length, narrowed, mode]);

  const empty = mode === '7'
    ? <Card><EmptyState title={NOTHING_LAST_7} action={<Button variant="quiet" onClick={() => setMode('30')}>{SHOW_LAST_30}</Button>} /></Card>
    : <Card><EmptyState title={NOTHING_MATCHED} body={NOTHING_MATCHED_BODY} /></Card>;

  function closeDetail() {
    const id = selected?.id;
    setSelected(null);
    if (id !== undefined) document.querySelector<HTMLElement>(`[data-testid=txn-row][data-id="${id}"]`)?.focus();
  }

  const detail = selected && <TxnDetail key={selected.id} txn={selected} today={today} onSaved={setSelected} onClose={closeDetail} showHeader={wide} />;

  return (
    <div className={`screen transactions${sel.on ? ' is-selecting' : ''}`}>
      {accountId === undefined ? (
        <>
          {/* A parent book's accounts, and the way here, are in its Inventory. */}
          <Link className="link back" to={household ? '/accounts' : '/inventory'}>
            <ChevronLeft className="i" size={20} aria-hidden="true" />{household ? ACCOUNTS : INVENTORY}
          </Link>
          <h1>{ALL_TRANSACTIONS}</h1>
        </>
      ) : head}
      <div className="split">
        <div className="split__list stack">
          <div className="search">
            <Field label={SEARCH} hint={SEARCH_HINT}>
              <input type="search" value={text} onChange={(e) => setText(e.target.value)} />
            </Field>
            <Search size={20} aria-hidden="true" />
          </div>
          {params.batch !== undefined && <Suspense fallback={null}><BatchBar batchId={params.batch} /></Suspense>}
          <Filters
            open={open}
            onOpen={setOpen}
            mode={mode}
            from={range.from ?? ''}
            to={range.to ?? ''}
            onMode={setMode}
            onCustom={(from, to) => update({ from, to }, true)}
            values={{ account_id: params.account_id, category: params.category, owner: params.owner, business: params.business, sorted: params.sorted }}
            accounts={accounts.data?.accounts ?? []}
            fixedAccount={accountId !== undefined}
            onChange={(c) => update(c)}
            extra={canEdit && rows.length > 0 && (
              <button ref={selectBtn} type="button" className={`filter filter--end${sel.on ? ' is-on' : ''}`} aria-pressed={sel.on}
                onClick={() => { if (sel.on) sel.end(); else startSelect(); }}>{SELECT}</button>
            )}
          />
          {txns.isError ? (
            <Notice tone="error">
              <p>{txns.error.message}</p>
              <Button variant="quiet" onClick={() => txns.refetch()}>{TRY_AGAIN}</Button>
            </Notice>
          ) : (
            <TxnList
              rows={rows}
              loading={txns.isPending}
              hasMore={!!txns.hasNextPage}
              loadingMore={txns.isFetchingNextPage}
              onMore={() => txns.fetchNextPage()}
              selectedId={selected?.id ?? null}
              onSelect={setSelected}
              empty={empty}
              today={today}
              selecting={sel.on}
              picked={sel.ids}
              onPick={sel.pick}
              onLongPress={canEdit ? startSelect : null}
            />
          )}
        </div>
        {wide && detail && <aside className="split__detail" aria-label="Transaction detail"><div className="detail-pane">{detail}</div></aside>}
      </div>
      {bulk && (
        <Suspense fallback={null}>
          <BulkSort selecting={sel.on} ids={pickedIds} onCancel={sel.end} onSorted={onBulkSorted} onUndone={refresh} home={() => selectBtn.current} />
        </Suspense>
      )}
      {!wide && selected && (
        <Sheet open onClose={() => setSelected(null)} title={txnLabel(selected)}>
          {detail}
        </Sheet>
      )}
    </div>
  );
}
