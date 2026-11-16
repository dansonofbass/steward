import { ChevronDown, ChevronLeft, CircleCheck, Eye, Flag, SlidersHorizontal, TriangleAlert } from 'lucide-react';
import { useSearchParams } from 'react-router-dom';
import { useBook, useCanEdit } from '../../book/BookContext';
import { Link } from '../../book/links';
import { TRY_AGAIN } from '../../lib/copy';
import { Button } from '../../ui/Button';
import { Card } from '../../ui/Card';
import { Notice } from '../../ui/Notice';
import { Skeleton } from '../../ui/Skeleton';
import { fill, parentName, possessive } from '../inventory/format';
import '../inventory/inventory.css';
import { useFlags, type FlagRow } from './api';
import * as C from './copy';
import { FlagRowLink } from './FlagRow';
import './watching.css';

/** Look into (spec 4.2; README screens 2 and 7). Home stays the current tab. */
export function LookInto() {
  const [params, setParams] = useSearchParams();
  const show = params.get('show') === 'done' ? 'done' : 'open';
  const check = params.get('check') ?? '';
  const account = params.get('account') ?? '';
  const q = useFlags(show, check || undefined, account || undefined);
  const canEdit = useCanEdit();
  const names = possessive(parentName(useBook()));
  const set = (k: string, v: string) => setParams((p) => { const n = new URLSearchParams(p); if (v) n.set(k, v); else n.delete(k); return n; }, { replace: true, preventScrollReset: true });
  const first = q.data?.pages[0];
  const rows: FlagRow[] = q.data?.pages.flatMap((p) => p.flags) ?? [];
  const urgent = rows.filter((r) => r.urgent);
  const other = rows.filter((r) => !r.urgent);
  const total = first?.checks.reduce((n, c) => n + c.count, 0) ?? 0;

  return (
    <div className="screen look-into">
      <header className="page-head">
        <Link className="link back" to="/"><ChevronLeft className="i" size={20} aria-hidden="true" />{C.BACK_HOME}</Link>
        <div className="page-head__row">
          <h1><Flag size={24} aria-hidden="true" />{C.LOOK_INTO}</h1>
          {canEdit && <Link className="link" to="/settings/watching"><SlidersHorizontal size={20} aria-hidden="true" />{C.WATCHING_SETTINGS}</Link>}
        </div>
        {!canEdit && <p className="readonly-line"><Eye size={20} aria-hidden="true" />{C.READ_ONLY}</p>}
        {first && <p className="muted">{fill(C.LIST_LEDE, { names })} {first.ran ? first.ran.line : C.NOT_RUN_YET}</p>}
      </header>

      <div className="toolbar">
        <div className="stack stack--tight">
          <span className="field__label">{C.SHOW}</span>
          <div className="filters" role="group" aria-label={C.SHOW}>
            <button className={`filter${show === 'open' ? ' is-on' : ''}`} type="button" aria-pressed={show === 'open'} onClick={() => setParams({}, { replace: true, preventScrollReset: true })}>
              <Flag size={20} aria-hidden="true" />{C.TO_LOOK_INTO} <span className="count-pill">{first?.counts.open ?? ''}</span>
            </button>
            <button className={`filter${show === 'done' ? ' is-on' : ''}`} type="button" aria-pressed={show === 'done'} onClick={() => setParams({ show: 'done' }, { replace: true, preventScrollReset: true })}>
              <CircleCheck size={20} aria-hidden="true" className="ok-mark" />{C.DONE} <span className="count-pill">{first?.counts.done ?? ''}</span>
            </button>
          </div>
        </div>
        <div className="grid-2">
          <div className="field select">
            <label className="field__label" htmlFor="li-check">{C.CHECK}</label>
            <select id="li-check" value={check} onChange={(e) => set('check', e.target.value)}>
              <option value="">{fill(C.ALL_CHECKS, { n: total })}</option>
              {first?.checks.map((c) => <option key={c.check} value={c.check}>{`${c.label} (${c.count})`}</option>)}
            </select>
            <ChevronDown size={20} aria-hidden="true" />
          </div>
          <div className="field select">
            <label className="field__label" htmlFor="li-account">{C.ACCOUNT}</label>
            <select id="li-account" value={account} onChange={(e) => set('account', e.target.value)}>
              <option value="">{C.ALL_ACCOUNTS}</option>
              {first?.accounts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
            </select>
            <ChevronDown size={20} aria-hidden="true" />
          </div>
        </div>
      </div>

      {q.isPending && <Card><Skeleton lines={6} /></Card>}
      {q.isError && <Notice tone="error"><p>{q.error.message}</p><Button variant="quiet" onClick={() => q.refetch()}>{TRY_AGAIN}</Button></Notice>}
      {q.isSuccess && rows.length === 0 && show === 'open' && (
        <div className="card attn"><div className="attn__main"><CircleCheck size={20} aria-hidden="true" className="ok-mark" />
          <span><strong>{C.NOTHING_TO_LOOK_INTO_DOT}</strong> <span className="muted">{first?.ran ? first.ran.empty : C.NOT_RUN_YET}</span></span></div></div>
      )}
      {q.isSuccess && rows.length === 0 && show === 'done' && <p className="muted">{C.NOTHING_DONE}</p>}
      {rows.length > 0 && show === 'open' && (
        <>
          <section className="card flags" aria-label={C.TO_LOOK_INTO}>
            {urgent.length > 0 && <div className="flags__group"><TriangleAlert size={20} aria-hidden="true" className="urg-icon" />{fill(C.GROUP_URGENT, { n: urgent.length })}</div>}
            {urgent.map((r) => <FlagRowLink key={r.id} row={r} />)}
            {other.length > 0 && <div className="flags__group"><Flag size={20} aria-hidden="true" />{fill(C.GROUP_OTHER, { n: other.length })}</div>}
            {other.map((r) => <FlagRowLink key={r.id} row={r} />)}
          </section>
          <p className="small muted">{C.LIST_FOOT}</p>
        </>
      )}
      {rows.length > 0 && show === 'done' && (
        <>
          <section className="card flags" aria-label={C.DONE}>{rows.map((r) => <FlagRowLink key={r.id} row={r} />)}</section>
          {q.hasNextPage && <div className="row-actions"><Button variant="quiet" busy={q.isFetchingNextPage} onClick={() => void q.fetchNextPage()}>{C.SHOW_OLDER}</Button></div>}
        </>
      )}
    </div>
  );
}

export default LookInto;
