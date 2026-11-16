import { ChevronDown, ChevronRight, Eye, List, ListPlus, Plus, Search } from 'lucide-react';
import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useBook, useCanEdit } from '../../book/BookContext';
import { Link } from '../../book/links';
import { ALL_TRANSACTIONS, INVENTORY, TRY_AGAIN, VIEWER_CANT_CHANGE } from '../../lib/copy';
import { Button } from '../../ui/Button';
import { EmptyState } from '../../ui/EmptyState';
import { Notice } from '../../ui/Notice';
import { Skeleton } from '../../ui/Skeleton';
import { useInventory, type ItemRow, type ItemStatus } from './api';
import {
  ADD_AN_ITEM, ALL, CHECKING_FOOT, EVERYONE, GROUP_LABELS, HEAD, INVENTORY_LEDE, IS_THIS_HERS_N, LIST_FOOT, NO_BALANCE,
  NOTHING_LISTED, NOTHING_LISTED_BODY, NOTHING_MATCHES, OWNER, SEARCH, SEARCH_PLACEHOLDER, STATUS,
} from './copy';
import { amountText, fill, groupTotal, KIND_ORDER, matches, parentName, possessive, updatedLabel } from './format';
import { KIND_ICONS, SourceMark, StatusMark } from './marks';
import '../accounts/accounts.css';
import './inventory.css';

type Filter = 'all' | ItemStatus;
const FILTERS: Filter[] = ['all', 'confirmed', 'needs_checking', 'closed'];

function Row({ r, today }: { r: ItemRow; today: Date }) {
  return (
    <Link className={`irow${r.status === 'closed' ? ' is-closed' : ''}`} to={`/inventory/${r.id}`} data-testid="item-row">
      <span className="irow__main"><span className="irow__name">{r.name}</span><span className="irow__sub">{r.sub}</span></span>
      <span className="irow__meta">
        <span className="owner">{r.owner_label}</span>
        <StatusMark status={r.status} />
        <SourceMark source={r.data_source} />
        <span>{updatedLabel(r.updated_on, today)}</span>
      </span>
      <span className="money money--m">{r.no_balance ? <span className="muted">{NO_BALANCE}</span> : amountText(r)}</span>
    </Link>
  );
}

export function InventoryList() {
  const book = useBook();
  const canEdit = useCanEdit();
  const inv = useInventory();
  const [sp, setSp] = useSearchParams();
  const [owner, setOwner] = useState('');
  const [q, setQ] = useState('');
  const status = (FILTERS.includes(sp.get('status') as Filter) ? sp.get('status') : 'all') as Filter;
  const setStatus = (f: Filter) => setSp(f === 'all' ? {} : { status: f }, { replace: true, preventScrollReset: true });
  const today = new Date();

  if (inv.isPending) return <div className="screen" aria-busy="true"><Skeleton lines={6} /></div>;
  if (inv.isError) {
    return <div className="screen"><Notice tone="error"><p>{inv.error.message}</p><Button variant="quiet" onClick={() => inv.refetch()}>{TRY_AGAIN}</Button></Notice></div>;
  }
  const { items, suggestions } = inv.data;
  const count = (f: Filter) => (f === 'all' ? items.length : items.filter((r) => r.status === f).length);
  const shown = items.filter((r) => (status === 'all' || r.status === status) && (!owner || r.owner === owner) && matches(r, q));
  const name = parentName(book);
  const names = possessive(name);

  return (
    <div className="screen inventory">
      <header className="page-head">
        <div className="page-head__row">
          <h1>{INVENTORY}</h1>
          {canEdit && <Link className="btn btn--primary" to="/inventory/new"><span className="btn__content"><Plus size={20} aria-hidden="true" /><span>{ADD_AN_ITEM}</span></span></Link>}
        </div>
        {canEdit
          ? <p className="muted">{fill(INVENTORY_LEDE, { name })}</p>
          : <p className="readonly-line"><Eye size={20} aria-hidden="true" />{VIEWER_CANT_CHANGE}</p>}
      </header>

      {canEdit && suggestions && (
        <Link className="card attn" to="/inventory/suggestions">
          <span className="attn__main"><ListPlus size={20} aria-hidden="true" /><span><strong>{fill(IS_THIS_HERS_N, { names, n: suggestions.count })}</strong> <span className="muted">· {suggestions.phrases.join(', ')}</span></span></span>
          <ChevronRight size={20} aria-hidden="true" />
        </Link>
      )}

      <div className="toolbar">
        <div className="stack stack--tight">
          <span className="field__label">{STATUS}</span>
          <div className="filters" role="group" aria-label={STATUS}>
            {FILTERS.map((f) => (
              <button key={f} type="button" className={`filter${status === f ? ' is-on' : ''}`} aria-pressed={status === f} onClick={() => setStatus(f)}>
                {f === 'all' ? ALL : <StatusMark status={f} />} <span className="count-pill">{count(f)}</span>
              </button>
            ))}
          </div>
        </div>
        <div className="grid-2">
          <div className="field select">
            <label className="field__label" htmlFor="inv-owner">{OWNER}</label>
            <select id="inv-owner" value={owner} onChange={(e) => setOwner(e.target.value)}>
              <option value="">{EVERYONE}</option>
              {(book?.owners ?? []).map((o) => <option key={o.key} value={o.key}>{o.label}</option>)}
            </select>
            <ChevronDown size={20} aria-hidden="true" />
          </div>
          <div className="field search">
            <label className="field__label" htmlFor="inv-search">{SEARCH}</label>
            <Search size={20} aria-hidden="true" />
            <input id="inv-search" value={q} placeholder={SEARCH_PLACEHOLDER} onChange={(e) => setQ(e.target.value)} />
          </div>
        </div>
      </div>

      <Link className="card all-row" to="/transactions?dates=all">
        <List size={24} aria-hidden="true" /><span>{ALL_TRANSACTIONS}</span><ChevronRight size={20} aria-hidden="true" />
      </Link>

      {items.length === 0 ? <EmptyState title={NOTHING_LISTED} body={fill(NOTHING_LISTED_BODY, { names })} />
        : shown.length === 0 ? <EmptyState title={NOTHING_MATCHES} />
          : (
            <div className="stack">
              {KIND_ORDER.map((kind) => {
                const rows = shown.filter((r) => r.kind === kind);
                if (rows.length === 0) return null;
                const Icon = KIND_ICONS[kind];
                const total = groupTotal(kind, rows);
                return (
                  <section key={kind} className="card igroup" aria-label={GROUP_LABELS[kind]}>
                    <div className="igroup__head">
                      <h2><Icon size={20} aria-hidden="true" />{GROUP_LABELS[kind]} <span className="count-pill">{rows.length}</span></h2>
                      {total && <span className="money">{total}</span>}
                    </div>
                    <div className="ihead" aria-hidden="true">
                      <span>{HEAD.item}</span><span>{HEAD.owner}</span><span>{HEAD.status}</span><span>{HEAD.from}</span><span>{HEAD.updated}</span><span>{HEAD.amount}</span>
                    </div>
                    {rows.map((r) => <Row key={r.id} r={r} today={today} />)}
                  </section>
                );
              })}
            </div>
          )}
      <p className="small muted">{status === 'needs_checking' ? CHECKING_FOOT : LIST_FOOT}</p>
    </div>
  );
}

export default InventoryList;
