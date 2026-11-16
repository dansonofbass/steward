import { useQueryClient } from '@tanstack/react-query';
import { ChevronLeft, ChevronRight, Settings as Gear } from 'lucide-react';
import { useState, type FormEvent } from 'react';
import { useBusiness } from '../../api/hooks';
import type { BusinessReport, ReportLine } from '../../api/types';
import { useCanEdit } from '../../book/BookContext';
import { Link } from '../../book/links';
import { HOME, SAVE, TRY_AGAIN } from '../../lib/copy';
import { dateLabel, dollars, money } from '../../lib/format';
import { radioKeys, radioTab } from '../../lib/radioKeys';
import { Button } from '../../ui/Button';
import { Card } from '../../ui/Card';
import { Field } from '../../ui/Field';
import { Money } from '../../ui/Money';
import { MoneyInput } from '../../ui/MoneyInput';
import { Notice } from '../../ui/Notice';
import { NotAdvice } from '../../ui/NotAdvice';
import { Skeleton } from '../../ui/Skeleton';
import { failure } from '../settings/shared';
import { toHundredths } from '../settings/money';
import { saveBusinessSettings } from './api';
import * as C from './copy';
import { LineSheet } from './LineSheet';
import { SCorpCard } from './SCorpCard';
import './business.css';

function RangeCard({ data }: { data: BusinessReport }) {
  const canEdit = useCanEdit();
  const qc = useQueryClient();
  const [editing, setEditing] = useState(!data.range.entered);
  const [low, setLow] = useState('');
  const [high, setHigh] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const r = data.range;

  async function save(e: FormEvent) {
    e.preventDefault();
    const lo = toHundredths(low);
    const hi = toHundredths(high);
    if ('error' in lo || 'error' in hi) { setError('error' in lo ? lo.error : (hi as { error: string }).error); return; }
    if (lo.value > hi.value) { setError(C.LOW_HIGH); return; }
    setBusy(true);
    setError(null);
    try {
      await saveBusinessSettings({ expect: { low_cents: lo.value, high_cents: hi.value } });
      setEditing(false);
      void qc.invalidateQueries({ queryKey: ['business'] });
      void qc.invalidateQueries({ queryKey: ['plan'] });
    } catch (err) {
      setError(failure(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="stack">
      <h2 className="eyebrow">{C.FULL_YEAR}</h2>
      {r.entered && <p className="biz-range">{C.RANGE.replace('{low}', dollars(r.low_cents)).replace('{high}', dollars(r.high_cents))}</p>}
      <p className="small muted">{r.entered ? C.RANGE_HOW : C.ADD_EXPECT}</p>
      {canEdit && (editing ? (
        <form className="stack" onSubmit={save}>
          <div className="biz-pair">
            <Field label={C.REST_LOW} hint={C.REST_HINT}><MoneyInput value={low} onValueChange={setLow} allowNegative /></Field>
            <Field label={C.REST_HIGH}><MoneyInput value={high} onValueChange={setHigh} allowNegative /></Field>
          </div>
          {error && <Notice tone="error">{error}</Notice>}
          <Button type="submit" busy={busy} disabled={!low || !high}>{SAVE}</Button>
        </form>
      ) : <Button variant="quiet" onClick={() => setEditing(true)}>{C.CHANGE}</Button>)}
    </Card>
  );
}

export default function Business() {
  const canEdit = useCanEdit();   // Settings, Business is a manager's
  const [year, setYear] = useState<number | null>(null);      // null: the household's this year, from the server
  const q = useBusiness(year);
  const [open, setOpen] = useState<ReportLine | null>(null);
  const today = new Date();

  const back = <Link className="link back" to="/"><ChevronLeft className="i" size={20} aria-hidden="true" />{HOME}</Link>;
  if (q.isError) {
    return <div className="screen business">{back}<Notice tone="error"><p>{q.error.message}</p><Button variant="quiet" onClick={() => void q.refetch()}>{TRY_AGAIN}</Button></Notice></div>;
  }
  if (!q.data) return <div className="screen business" aria-busy="true">{back}<Skeleton lines={6} /></div>;
  const data = q.data;
  const thisYear = data.this_year;
  if (data.type === 'none') {
    return (
      <div className="screen business">
        {back}
        <h1>{C.BUSINESS_TITLE}</h1>
        <Card className="stack">{canEdit ? <><p>{C.OFF}</p><Link className="link" to="/settings/business">{C.TURN_ON}</Link></> : <p>{C.OFF_VIEWER}</p>}</Card>
      </div>
    );
  }
  const income = data.lines.find((l) => l.key === 'income');
  // An expense is money out but is listed as a positive figure: plain ink, never the money-in green.
  const plain = (cents: number) => <span className="money money--m">{money(cents)}</span>;
  const costs = data.lines.filter((l) => l.key !== 'income');
  const rows = (n: number) => (n === 1 ? C.ROWS_ONE : C.ROWS_N.replace('{n}', String(n)));
  // The home office has no transactions; a manager goes to where it is set, a viewer just reads it.
  const homeOffice = (l: ReportLine) => (
    <>
      <span className="biz-line__name">{l.label}<span className="small muted">{C.LINE_N.replace('{n}', l.number)}</span></span>
      {plain(l.counts_cents)}
      <span className="small muted biz-line__note">{l.note ?? C.FROM_SETTINGS}</span>
      {canEdit && <ChevronRight className="biz-line__go" size={20} aria-hidden="true" />}
    </>
  );
  const lineButton = (l: ReportLine) => (
    <li key={l.key}>
      {l.key === 'home_office' ? (
        canEdit ? <Link className="biz-line" to="/settings/business">{homeOffice(l)}</Link> : <div className="biz-line">{homeOffice(l)}</div>
      ) : (
        <button type="button" className="biz-line" onClick={() => setOpen(l)}>
          <span className="biz-line__name">{l.label}<span className="small muted">{C.LINE_N.replace('{n}', l.number)}</span></span>
          {l.key === 'income' ? <Money cents={l.counts_cents} /> : plain(l.counts_cents)}
          <span className="small muted biz-line__note">{rows(l.count)}</span>
          {l.note && <span className="small muted biz-line__note">{l.note}</span>}
          <ChevronRight className="biz-line__go" size={20} aria-hidden="true" />
        </button>
      )}
    </li>
  );

  return (
    <div className="screen business">
      {back}
      <h1>{C.BUSINESS_TITLE}</h1>
      <div className="seg biz-years" role="radiogroup" aria-label={C.YEARS} onKeyDown={radioKeys}>
        {[thisYear, thisYear - 1].map((y) => (
          <button key={y} type="button" role="radio" aria-checked={data.year === y} tabIndex={radioTab(data.year === y)} className={data.year === y ? 'is-on' : ''} onClick={() => setYear(y)}>{y}</button>
        ))}
      </div>
      <Card className="stack">
        <h2 className="eyebrow">{C.SO_FAR.replace('{year}', String(data.year))}</h2>
        <dl className="biz-sum">
          <div><dt>{C.INCOME}</dt><dd><Money cents={data.income_cents} /></dd></div>
          <div><dt>{C.EXPENSES}</dt><dd>{plain(data.expenses_cents)}</dd></div>
          <div><dt>{C.PROFIT}</dt><dd><Money cents={data.profit_cents} size="l" /></dd></div>
        </dl>
        <p className="small muted">{C.THROUGH.replace('{date}', dateLabel(data.through, today))}{data.using_note ? ` · ${data.using_note}` : ''}</p>
        {data.range.cash_ytd_cents !== data.profit_cents && <p className="small muted">{C.CASH_NOTE.replace('{cash}', money(data.range.cash_ytd_cents))}</p>}
      </Card>
      {data.year === thisYear && <RangeCard data={data} />}
      {data.lines.length === 0 ? <p className="muted">{C.NOTHING_YET.replace('{year}', String(data.year))}</p> : (
        <section className="stack" aria-labelledby="biz-lines">
          <h2 id="biz-lines">{C.BY_LINE}</h2>
          <ul className="biz-lines">{income && lineButton(income)}{costs.map(lineButton)}</ul>
          {data.home_office_limited && <p className="small muted">{C.LIMITED}</p>}
          {data.left_out > 0 && <p className="small muted">{data.left_out === 1 ? C.LEFT_OUT_ONE : C.LEFT_OUT_N.replace('{n}', String(data.left_out))}</p>}
        </section>
      )}
      <SCorpCard year={data.year} />
      {canEdit && <Link className="link biz-settings" to="/settings/business"><Gear size={20} aria-hidden="true" />{C.SETTINGS_LINK}</Link>}
      <NotAdvice />
      <LineSheet year={data.year} line={open} onClose={() => setOpen(null)} />
    </div>
  );
}
