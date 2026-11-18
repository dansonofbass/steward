import { ArrowDownLeft, ArrowUpRight, ChevronRight, CircleDashed, House, ListPlus, PiggyBank, Scale, TrendingUp, Wallet, type LucideIcon } from 'lucide-react';
import { useEffect, useRef } from 'react';
import { useLocation } from 'react-router-dom';
import { useSummary } from '../../api/hooks';
import { useBook } from '../../book/BookContext';
import { Link } from '../../book/links';
import { moneyParts, money } from '../../lib/format';
import { JOINED_BOOK, TRY_AGAIN } from '../../lib/copy';
import { Button } from '../../ui/Button';
import { Notice } from '../../ui/Notice';
import { Skeleton } from '../../ui/Skeleton';
import { Attention } from '../home/Attention';
import { useOverview, type TotalGroup } from './api';
import * as C from './copy';
import { fill, parentName, possessive } from './format';
import { CHANGE_ICONS, StatusMark } from './marks';
import './inventory.css';
import './hero.css';
import { FlagsBlock } from '../watching/FlagsBlock';
import { GatewayOffLine } from '../home/GatewayOffLine';

const TOTAL_ICONS: Record<TotalGroup, LucideIcon> = { cash: Wallet, investments: TrendingUp, retirement: PiggyBank, property: House, debts: Scale };
const when = (iso: string) => new Date(iso).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });

export function ParentHome() {
  const ov = useOverview();
  const summary = useSummary();
  const book = useBook();
  const name = parentName(book);
  const joined = (useLocation().state as { joined?: string } | null)?.joined;
  const marked = useRef(false);
  useEffect(() => {
    if (ov.isSuccess && !marked.current) { marked.current = true; performance.mark('home-ready'); }
  }, [ov.isSuccess]);
  if (ov.isPending) return <div className="screen home" aria-busy="true"><Skeleton lines={8} /></div>;
  if (ov.isError) return <div className="screen home"><Notice tone="error"><p>{ov.error.message}</p><Button variant="quiet" onClick={() => ov.refetch()}>{TRY_AGAIN}</Button></Notice></div>;
  const o = ov.data;
  const parts = moneyParts(o.net_worth_cents);
  const has = fill(C.WHAT_SHE_HAS, { name });

  return (
    <div className="screen home parent-home">
      {/* The screen's one level 1 heading (issue #21): the book's name, for a screen reader. The design opens on the
          figures, with no title. */}
      <h1 className="sr-only">{book?.name ?? name}</h1>
      {joined && <Notice>{JOINED_BOOK.replace('{name}', joined)}</Notice>}
      <GatewayOffLine />
      <FlagsBlock />
      <section className="hero" aria-label={C.NET_WORTH_KNOWN}>
        <div className="figure">
          <p className="eyebrow">{C.NET_WORTH_KNOWN}</p>
          {/* A paragraph can't carry a label (T7): the amount in words is its own text, for a screen reader. */}
          <p className="money-parts" data-testid="net-worth">
            <span className="sr-only">{money(o.net_worth_cents)}</span>
            <span className="money-parts__sym" aria-hidden="true">{parts.sign}$</span><span aria-hidden="true">{parts.dollars}</span><span className="money-parts__cents" aria-hidden="true">.{parts.cents}</span>
          </p>
          <p className="small muted">{o.counted_line}</p>
        </div>
        {o.fresh_line && <p className="small muted">{o.fresh_line}</p>}
      </section>

      <section className="stack stack--tight" aria-label={C.TO_DO}>
        {o.needs_checking.count > 0 && (
          <div className="card attn">
            <div className="attn__main"><CircleDashed size={20} aria-hidden="true" /><span><strong>{fill(C.NEEDS_CHECKING_N, { n: o.needs_checking.count })}</strong> <span className="muted">· {o.needs_checking.labels.join(', ')}</span></span></div>
            <Link className="btn btn--quiet" to="/inventory?status=needs_checking"><span className="btn__content"><span>{C.SEE_THEM}</span><ChevronRight size={20} aria-hidden="true" /></span></Link>
          </div>
        )}
        {o.suggestions && (
          <div className="card attn">
            <div className="attn__main"><ListPlus size={20} aria-hidden="true" /><span><strong>{fill(C.IS_THIS_HERS_N, { names: possessive(name), n: o.suggestions.count })}</strong> <span className="muted">· {o.suggestions.found_in}</span></span></div>
            <Link className="btn btn--quiet" to="/inventory/suggestions"><span className="btn__content"><span>{C.GO_THROUGH}</span><ChevronRight size={20} aria-hidden="true" /></span></Link>
          </div>
        )}
        {summary.data && <Attention items={summary.data.needs_attention} />}
      </section>

      <section className="stack" aria-label={has}>
        <div className="section-head"><h2>{has}</h2><Link className="link" to="/inventory">{C.BACK_TO_INVENTORY}<ChevronRight size={20} aria-hidden="true" /></Link></div>
        <div className="totals">
          {o.totals.map((t) => {
            const Icon = TOTAL_ICONS[t.key];
            return (
              <Link key={t.key} className={`card total${t.key === 'debts' ? ' is-debt' : ''}`} to="/inventory">
                <span className="total__k"><Icon size={20} aria-hidden="true" />{t.label}</span>
                <span className="total__v">{money(t.cents)}</span>
                <span className="total__n">{t.note}</span>
              </Link>
            );
          })}
        </div>
      </section>

      <section className="flows" aria-label={C.MONEY_IN_OUT}>
        {([['in', C.COMING_IN, ArrowDownLeft, o.incoming, null], ['out', C.GOING_OUT, ArrowUpRight, o.outgoing, C.A_MONTH]] as const).map(([key, title, Icon, flow, per]) => (
          <div key={key} className="card flowbox">
            <div className="flowbox__head">
              <h2><Icon size={20} aria-hidden="true" />{title}</h2>
              <span className={`money${key === 'in' ? ' money--in' : ''}`}>{money(flow.monthly_cents)}{per && <span className="small muted"> {per}</span>}</span>
            </div>
            {flow.rows.map((r) => (
              <Link key={r.item_id} className="fl" to={`/inventory/${r.item_id}`}>
                <span className="fl__name">{r.name}</span>
                <span className={`money money--m${key === 'in' ? ' money--in' : ''}`}>{money(r.cents)}</span>
                <span className="fl__sub">{r.sub}{r.status === 'needs_checking' && <> <StatusMark status={r.status} /></>}</span>
                <span className="fl__per">{r.per}</span>
              </Link>
            ))}
            {flow.foot && <p className="flowbox__foot">{flow.foot}</p>}
          </div>
        ))}
      </section>

      <section className="stack stack--tight" aria-label={C.RECENT_CHANGES}>
        <div className="section-head"><h2>{C.RECENT_CHANGES}</h2><Link className="link" to="/settings/changes">{C.CHANGE_RECORD}<ChevronRight size={20} aria-hidden="true" /></Link></div>
        <div className="card lines">
          {o.recent.length === 0 && <p className="small muted">{C.NO_CHANGES_YET}</p>}
          {o.recent.map((r) => {
            const Icon = CHANGE_ICONS[r.icon] ?? CHANGE_ICONS.pencil;
            return (
              <div key={r.id} className="line"><div className="line__lead"><Icon size={20} aria-hidden="true" /><div className="line__main"><span>{r.summary}</span><span className="small muted">{when(r.at)}</span></div></div></div>
            );
          })}
        </div>
      </section>
    </div>
  );
}

export default ParentHome;
