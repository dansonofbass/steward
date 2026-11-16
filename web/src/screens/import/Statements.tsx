import { useQuery, useQueryClient } from '@tanstack/react-query';
import { X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { api, json } from '../../api/client';
import { gw } from '../../lib/gatewayName';
import { Button } from '../../ui/Button';
import { Notice } from '../../ui/Notice';
import { failure } from '../settings/shared';
import * as C from './copy';
import { monthDay } from './logic';
import { money, patchStatement, type StatementLine } from './statements';

type Row = { i: number; scan?: boolean; date: string; description: string; amount_cents: number; page: number | null; section: string | null;
  state: 'read' | 'edited' | 'added' | 'removed' };
type Holding = { i: number; symbol: string | null; name: string | null; shares_milli: number | null; value_cents: number; cash: boolean;
  page: number | null; state: 'read' | 'edited' | 'added' | 'removed' };
type Section = { title: string; rows: number; sum_cents: number; total_cents: number | null };
type Detail = {
  id: number; state: string; gap_cents: number | null; anyway: boolean; pages: number | null;
  statement: { kind: string; institution: string; label: string | null; last4: string | null; period: [string, string] | null;
    opening_cents: number | null; closing_cents: number | null; total_cents?: number | null; opening_label: string; closing_label: string };
  holdings: Holding[];
  /** An investment scan read for rows because the gateway can't read holdings yet. */
  holdings_update?: boolean;
  rows: Row[]; sections: Section[]; unreadable: { page: number; text: string }[];
};
type Op = { op: 'edit'; i: number; date?: string; description?: string; amount_cents?: number } | { op: 'remove' | 'restore'; i: number }
  | { op: 'add'; date: string; description: string; amount_cents: number };
type Reply = { state: StatementLine['state']; gap_cents: number | null; sections: Section[]; rows: Row[] };

const OWED = new Set(['card', 'loan']);
/** As the statement prints it: a card's purchases positive (stored × −1); a bank's money out negative. */
const printed = (kind: string, cents: number) => (OWED.has(kind) ? -cents : cents);
const signed = (cents: number) => (cents < 0 ? '-' : '') + money(cents).slice(1);
function toCents(text: string): number | null {
  const t = text.trim().replace(/[$,\s]/g, '');
  return /^-?\d+(\.\d{1,2})?$/.test(t) ? Math.round(Number(t) * 100) : null;
}
type HoldingOp = { op: 'edit'; i: number; symbol?: string; name?: string; shares_milli?: number; value_cents?: number }
  | { op: 'remove' | 'restore'; i: number } | { op: 'add'; symbol: string; name: string; shares_milli: number; value_cents: number };
const HOLDING_KINDS = new Set(['investment', 'retirement']);
const DAYS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const day = (iso: string) => { const [, m, d] = iso.split('-').map(Number); return `${DAYS[m - 1]} ${d}`; };
const sharesText = (milli: number | null) => (milli ? (milli / 1000).toLocaleString('en-US', { maximumFractionDigits: 3 }) : '');
const toMilli = (text: string): number | null => {
  const t = text.trim().replace(/,/g, '');
  return t === '' ? 0 : /^\d+(\.\d{1,3})?$/.test(t) ? Math.round(Number(t) * 1000) : null;
};
function holdingsLine(gap: number | null) {
  if (gap === 0) return C.HOLDINGS_ADD_UP;
  if (gap === null) return C.CHECK_HOLDINGS;
  return (gap > 0 ? C.HOLDINGS_SHORT : C.HOLDINGS_OVER).replace('{gap}', money(Math.abs(gap)));
}
const rowsWord = (n: number) => (n === 1 ? C.ROWS_ONE : C.ROWS_N.replace('{n}', String(n)));

type Props = {
  line: StatementLine; onDone: (to: StatementLine['state']) => void;
  /** Runs a request that changes the staged statement through the screen, which keeps Preview waiting until it has settled. */
  track?: <T>(p: Promise<T>) => Promise<T>;
};
const direct = <T,>(p: Promise<T>) => p;

/** The layout check and row review (spec, Screen: Import, with statements), loaded when a line needs a look. `onDone`
 *  says which state the line has reached, so the screen can put focus where the spec says. */
export default function Statements({ line, onDone, track = direct }: Props) {
  // Never from cache: the review copies the rows once, so a reopened line must show what the book holds now.
  const q = useQuery({ queryKey: ['statement', line.id, line.state], queryFn: () => api<Detail>(`/api/import/statements/${line.id}`),
    gcTime: 0, staleTime: 0 });
  if (q.error) return <Notice tone="error">{failure(q.error)}</Notice>;
  if (!q.data) return <div aria-busy="true" />;
  const d = q.data;
  if (HOLDING_KINDS.has(d.statement.kind)) {
    return d.state === 'holdings' ? <HoldingsCheck line={line} d={d} onDone={onDone} />
      : <HoldingsReview line={line} d={d} onDone={onDone} track={track} />;
  }
  return d.state === 'layout'
    ? <LayoutCheck line={line} d={d} onDone={onDone} />
    : <RowReview line={line} d={d} onDone={onDone} track={track} />;
}

/** Looks right / Not right, as the layout check and the holdings check both post them. */
function useLayoutAnswer(line: StatementLine, onDone: Props['onDone']) {
  const qc = useQueryClient();
  const [busy, setBusy] = useState<'right' | 'wrong' | null>(null);
  const [error, setError] = useState('');
  async function answer(a: 'right' | 'wrong') {
    setBusy(a);
    setError('');
    try {
      const r = await api<{ statement: StatementLine }>(`/api/import/statements/${line.id}/layout`, json({ answer: a }));
      await qc.invalidateQueries({ queryKey: ['statements'] });
      if (a === 'right') onDone(r.statement.state);
      else await qc.invalidateQueries({ queryKey: ['statement', line.id] });
    } catch (e) {
      setError(failure(e));
      setBusy(null);
    }
  }
  return { busy, error, answer };
}

function Answer({ a }: { a: ReturnType<typeof useLayoutAnswer> }) {
  return (
    <>
      {a.error && <Notice tone="error">{a.error}</Notice>}
      <div className="row-actions">
        <Button busy={a.busy === 'right'} onClick={() => void a.answer('right')}>{C.LOOKS_RIGHT}</Button>
        <Button variant="quiet" busy={a.busy === 'wrong'} onClick={() => void a.answer('wrong')}>{C.NOT_RIGHT}</Button>
      </div>
    </>
  );
}

function LayoutCheck({ line, d, onDone }: Props & { d: Detail }) {
  const a = useLayoutAnswer(line, onDone);
  const s = d.statement;
  const live = d.rows.filter((r) => r.state !== 'removed');
  return (
    <section className="imp-st" aria-label={C.LAYOUT_REGION.replace('{file}', line.name)}>
      <p className="imp-st__check">{s.kind === 'loan'
        ? C.LOAN_BALANCE.replace('{label}', s.closing_label).replace('{amount}', money(s.closing_cents ?? 0))
        : C.LAYOUT_CHECK.replace('{opening}', s.opening_label).replace('{a}', money(s.opening_cents ?? 0))
          .replace('{closing}', s.closing_label).replace('{b}', money(s.closing_cents ?? 0))}</p>
      {d.sections.map((sec) => {
        const rows = live.filter((r) => r.section === sec.title);
        return (
          <div key={sec.title} className="imp-st__section">
            <h4>{sec.title} <span className="muted small">{rowsWord(rows.length)}</span></h4>
            <div className="table-wrap">
              <table className="table imp-st__table">
                <caption className="sr-only">{sec.title}</caption>
                <tbody>{rows.map((r) => (
                  <tr key={r.i}><td>{monthDay(r.date)}</td><td>{r.description}</td>
                    <td className="num">{signed(printed(s.kind, r.amount_cents))}</td></tr>
                ))}</tbody>
              </table>
            </div>
          </div>
        );
      })}
      <p className="small muted">{C.LAYOUT_REMEMBERED}</p>
      <Answer a={a} />
    </section>
  );
}

function HoldingsCheck({ line, d, onDone }: Props & { d: Detail }) {
  const a = useLayoutAnswer(line, onDone);
  const s = d.statement;
  const live = d.holdings.filter((h) => h.state !== 'removed');
  const symbols = live.some((h) => h.symbol);     // a retirement plan's funds have names alone
  return (
    <section className="imp-st" aria-label={C.LAYOUT_REGION.replace('{file}', line.name)}>
      <p className="imp-st__check">{C.ENDING.replace('{amount}', money(s.closing_cents ?? 0)).replace('{date}', s.period ? day(s.period[1]) : '')}</p>
      <div className="table-wrap">
        <table className="table imp-st__table">
          <caption className="sr-only">{C.HOLDINGS_CAPTION.replace('{file}', line.name)}</caption>
          <thead><tr>{C.HOLDINGS_COLUMNS.filter((c) => symbols || c !== 'Symbol').map((c) => <th key={c} scope="col" className={c === 'Shares' || c === 'Value' ? 'num' : undefined}>{c}</th>)}</tr></thead>
          <tbody>{live.map((h) => (
            <tr key={h.i}>{symbols && <td>{h.symbol}</td>}<td>{h.name}</td><td className="num">{sharesText(h.shares_milli)}</td><td className="num">{money(h.value_cents)}</td></tr>
          ))}</tbody>
        </table>
      </div>
      <p className="imp-st__check">{holdingsLine(d.gap_cents)}</p>
      <p className="small muted">{C.LAYOUT_REMEMBERED}</p>
      <Answer a={a} />
    </section>
  );
}

function HoldingsReview({ line, d, onDone, track = direct }: Props & { d: Detail }) {
  const qc = useQueryClient();
  const [rows, setRows] = useState<Holding[]>(d.holdings);
  const [gap, setGap] = useState<number | null>(d.gap_cents);
  const [anyway, setAnyway] = useState(d.anyway);
  const [draft, setDraft] = useState<{ symbol: string; name: string; shares: string; value: string } | null>(null);
  const [error, setError] = useState('');
  const [undoAt, setUndoAt] = useState<number | null>(null);
  const gapRef = useRef<HTMLParagraphElement>(null);
  const undoRef = useRef<HTMLButtonElement>(null);
  useEffect(() => { gapRef.current?.focus(); }, []);
  useEffect(() => { if (undoAt !== null) undoRef.current?.focus(); }, [undoAt, rows]);

  async function send(ops: HoldingOp[], done = false): Promise<{ state: StatementLine['state'] } | null> {
    setError('');
    try {
      const r = await track(api<{ state: StatementLine['state']; gap_cents: number | null; holdings: Holding[] }>(
        `/api/import/statements/${line.id}/holdings`, json(done ? { ops, done } : { ops })));
      setRows(r.holdings);
      setGap(r.gap_cents);
      return r;
    } catch (e) {
      setError(failure(e));
      return null;
    }
  }
  function edit(h: Holding, field: 'symbol' | 'name' | 'shares' | 'value', text: string) {
    if (field === 'value') {
      const c = toCents(text);
      if (c !== null && c !== h.value_cents) void send([{ op: 'edit', i: h.i, value_cents: c }]);
    } else if (field === 'shares') {
      const m = toMilli(text);
      if (m !== null && m !== (h.shares_milli ?? 0)) void send([{ op: 'edit', i: h.i, shares_milli: m }]);
    } else if (text.trim() !== (h[field] ?? '')) void send([{ op: 'edit', i: h.i, [field]: text.trim() }]);
  }
  async function addDraft() {
    const c = draft && toCents(draft.value);
    const m = draft && toMilli(draft.shares);
    if (!draft || c === null || m === null || !(draft.symbol.trim() || draft.name.trim())) return;
    if (await send([{ op: 'add', symbol: draft.symbol.trim(), name: draft.name.trim(), shares_milli: m, value_cents: c }])) setDraft(null);
  }
  async function done() {
    const r = await send([], true);
    if (!r) return;
    await qc.invalidateQueries({ queryKey: ['statements'] });
    onDone(r.state);
  }
  async function toggleAnyway(on: boolean) {
    setAnyway(on);
    try {
      await track(patchStatement(line.id, { anyway: on }));
    } catch (e) {
      setAnyway(!on);
      setError(failure(e));
    }
  }
  const label = (column: string, n: number) => C.REVIEW_CELL.replace('{column}', column).replace('{n}', String(n));
  return (
    <section className="imp-st" aria-label={C.REVIEW_REGION.replace('{file}', line.name)}>
      <p className="imp-st__gap" aria-live="polite" tabIndex={-1} ref={gapRef}>{holdingsLine(gap)}</p>
      {d.holdings_update && <p className="small muted">{gw(C.ST_OLD_HOLDINGS)}</p>}
      <div className="table-wrap">
        <table className="table imp-st__review imp-st__held">
          <caption className="sr-only">{C.HOLDINGS_CAPTION.replace('{file}', line.name)}</caption>
          <thead><tr>{C.HOLDINGS_COLUMNS.map((c) => <th key={c} scope="col">{c}</th>)}<th scope="col"><span className="sr-only">{C.REMOVE.replace(' {file}', '')}</span></th></tr></thead>
          <tbody>
            {rows.map((h, k) => (h.state === 'removed' ? (
              <tr key={h.i} className="imp-st__rm"><td colSpan={5}>
                <button type="button" className="link" ref={undoAt === h.i ? undoRef : undefined}
                  onClick={() => { setUndoAt(null); void send([{ op: 'restore', i: h.i }]); }}>{C.REVIEW_REMOVED}</button>
              </td></tr>
            ) : (
              <tr key={h.i}>
                <td><input aria-label={label('Symbol', k + 1)} defaultValue={h.symbol ?? ''} maxLength={20} onBlur={(e) => edit(h, 'symbol', e.target.value)} /></td>
                <td><input aria-label={label('Name', k + 1)} defaultValue={h.name ?? ''} maxLength={200} onBlur={(e) => edit(h, 'name', e.target.value)} /></td>
                <td><input inputMode="decimal" aria-label={label('Shares', k + 1)} className="num" defaultValue={sharesText(h.shares_milli)}
                  onBlur={(e) => edit(h, 'shares', e.target.value)} /></td>
                <td><input inputMode="decimal" aria-label={label('Value', k + 1)} className="num" defaultValue={signed(h.value_cents)}
                  onBlur={(e) => edit(h, 'value', e.target.value)} /></td>
                <td><button type="button" className="icon-btn" aria-label={C.REVIEW_REMOVE.replace('{n}', String(k + 1))}
                  onClick={() => { setUndoAt(h.i); void send([{ op: 'remove', i: h.i }]); }}><X size={20} aria-hidden="true" /></button></td>
              </tr>
            )))}
            {draft && (
              <tr>
                <td><input aria-label={label('Symbol', rows.length + 1)} value={draft.symbol} maxLength={20}
                  onChange={(e) => setDraft({ ...draft, symbol: e.target.value })} onBlur={() => void addDraft()} /></td>
                <td><input aria-label={label('Name', rows.length + 1)} value={draft.name} maxLength={200}
                  onChange={(e) => setDraft({ ...draft, name: e.target.value })} onBlur={() => void addDraft()} /></td>
                <td><input inputMode="decimal" aria-label={label('Shares', rows.length + 1)} className="num" value={draft.shares}
                  onChange={(e) => setDraft({ ...draft, shares: e.target.value })} onBlur={() => void addDraft()} /></td>
                <td><input inputMode="decimal" aria-label={label('Value', rows.length + 1)} className="num" value={draft.value}
                  onChange={(e) => setDraft({ ...draft, value: e.target.value })} onBlur={() => void addDraft()} /></td>
                <td />
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {error && <Notice tone="error">{error}</Notice>}
      <div className="row-actions">
        <Button variant="quiet" onClick={() => setDraft({ symbol: '', name: '', shares: '', value: '' })} disabled={!!draft}>{C.ADD_ROW}</Button>
        {gap !== 0 && (
          <label className="imp-confirm__choice">
            <input type="checkbox" checked={anyway} onChange={(e) => void toggleAnyway(e.target.checked)} />{C.IMPORT_ANYWAY}
          </label>
        )}
        <Button onClick={() => void done()}>{C.DONE}</Button>
      </div>
    </section>
  );
}

function RowReview({ line, d, onDone, track = direct }: Props & { d: Detail }) {
  const qc = useQueryClient();
  const kind = d.statement.kind;
  const [rows, setRows] = useState<Row[]>(d.rows);
  const [gap, setGap] = useState<number | null>(d.gap_cents);
  const [sections, setSections] = useState<Section[]>(d.sections);
  const [anyway, setAnyway] = useState(d.anyway);
  const [draft, setDraft] = useState<{ date: string; description: string; amount: string } | null>(null);
  const [error, setError] = useState('');
  const [undoAt, setUndoAt] = useState<number | null>(null);
  const gapRef = useRef<HTMLParagraphElement>(null);
  const undoRef = useRef<HTMLButtonElement>(null);
  useEffect(() => { gapRef.current?.focus(); }, []);
  // The row collapses only when the reply lands, so the Undo button exists after `rows` changes, not when the click set undoAt.
  useEffect(() => { if (undoAt !== null) undoRef.current?.focus(); }, [undoAt, rows]);

  async function send(ops: Op[], done = false): Promise<Reply | null> {
    setError('');
    try {
      const r = await track(api<Reply>(`/api/import/statements/${line.id}/rows`, json(done ? { ops, done } : { ops })));
      setRows(r.rows);
      setGap(r.gap_cents);
      setSections(r.sections);
      return r;
    } catch (e) {
      setError(failure(e));
      return null;
    }
  }
  function edit(r: Row, field: 'date' | 'description' | 'amount', value: string) {
    if (field === 'amount') {
      const c = toCents(value);
      if (c === null || printed(kind, r.amount_cents) === c) return;
      void send([{ op: 'edit', i: r.i, amount_cents: printed(kind, c) }]);
    } else if (value.trim() && value !== r[field]) void send([{ op: 'edit', i: r.i, [field]: value.trim() }]);
  }
  async function addDraft() {
    const c = draft && toCents(draft.amount);
    if (!draft || c === null || !draft.date || !draft.description.trim()) return;
    if (await send([{ op: 'add', date: draft.date, description: draft.description.trim(), amount_cents: printed(kind, c) }])) setDraft(null);
  }
  async function done() {
    const r = await send([], true);
    if (!r) return;
    await qc.invalidateQueries({ queryKey: ['statements'] });
    onDone(r.state);
  }
  async function toggleAnyway(on: boolean) {
    setAnyway(on);
    try {
      await track(patchStatement(line.id, { anyway: on }));
    } catch (e) {
      setAnyway(!on);
      setError(failure(e));
    }
  }
  const off = sections.filter((s) => s.total_cents !== null && s.total_cents !== s.sum_cents);
  const gapText = gap === 0 ? C.REVIEW_ADDS_UP : gap === null ? C.ST_CHECK_ROWS : C.REVIEW_OFF.replace('{gap}', money(gap));
  const sectionText = gap ? off.map((s) => ' · ' + C.REVIEW_SECTION.replace('{section}', s.title)
    .replace('{gap}', money(s.total_cents! - s.sum_cents))).join('') : '';
  const label = (column: string, n: number) => C.REVIEW_CELL.replace('{column}', column).replace('{n}', String(n));
  return (
    <section className="imp-st" aria-label={C.REVIEW_REGION.replace('{file}', line.name)}>
      <p className="imp-st__gap" aria-live="polite" tabIndex={-1} ref={gapRef}>{gapText}{sectionText}</p>
      {d.unreadable.map((u) => <p key={`${u.page}-${u.text}`} className="small imp-row__tag--warn">
        {C.UNREADABLE_LINE.replace('{n}', String(u.page)).replace('{text}', u.text)}</p>)}
      {rows.some((r) => r.scan) && <p className="small muted">{C.SCAN_NOTE}</p>}
      {rows.some((r) => r.scan) && <span id={`scan-${line.id}`} className="sr-only">{C.SCAN_CELL}</span>}
      <div className="table-wrap">
        <table className="table imp-st__review">
          <caption className="sr-only">{C.ROWS_CAPTION.replace('{file}', line.name)}</caption>
          <thead><tr>{C.REVIEW_COLUMNS.map((c) => <th key={c} scope="col">{c}</th>)}<th scope="col"><span className="sr-only">{C.REMOVE.replace(' {file}', '')}</span></th></tr></thead>
          <tbody>
            {rows.map((r, k) => (r.state === 'removed' ? (
              <tr key={r.i} className="imp-st__rm"><td colSpan={5}>
                <button type="button" className="link" ref={undoAt === r.i ? undoRef : undefined}
                  onClick={() => { setUndoAt(null); void send([{ op: 'restore', i: r.i }]); }}>{C.REVIEW_REMOVED}</button>
              </td></tr>
            ) : (
              <tr key={r.i}>
                <td><input type="date" aria-label={label('Date', k + 1)} defaultValue={r.date} onBlur={(e) => edit(r, 'date', e.target.value)} /></td>
                <td><input aria-label={label('Description', k + 1)} defaultValue={r.description} maxLength={200}
                  {...(r.scan ? { className: 'imp-st__scan', 'aria-describedby': `scan-${line.id}` } : {})} onBlur={(e) => edit(r, 'description', e.target.value)} /></td>
                <td><input inputMode="decimal" aria-label={label('Amount', k + 1)} className="num"
                  defaultValue={signed(printed(kind, r.amount_cents))} onBlur={(e) => edit(r, 'amount', e.target.value)} /></td>
                <td className="num">{r.page ?? ''}</td>
                <td><button type="button" className="icon-btn" aria-label={C.REVIEW_REMOVE.replace('{n}', String(k + 1))}
                  onClick={() => { setUndoAt(r.i); void send([{ op: 'remove', i: r.i }]); }}><X size={20} aria-hidden="true" /></button></td>
              </tr>
            )))}
            {draft && (
              <tr>
                <td><input type="date" aria-label={label('Date', rows.length + 1)} value={draft.date}
                  onChange={(e) => setDraft({ ...draft, date: e.target.value })} onBlur={() => void addDraft()} /></td>
                <td><input aria-label={label('Description', rows.length + 1)} value={draft.description} maxLength={200}
                  onChange={(e) => setDraft({ ...draft, description: e.target.value })} onBlur={() => void addDraft()} /></td>
                <td><input inputMode="decimal" aria-label={label('Amount', rows.length + 1)} className="num" value={draft.amount}
                  onChange={(e) => setDraft({ ...draft, amount: e.target.value })} onBlur={() => void addDraft()} /></td>
                <td colSpan={2} />
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {error && <Notice tone="error">{error}</Notice>}
      <div className="row-actions">
        <Button variant="quiet" onClick={() => setDraft({ date: '', description: '', amount: '' })} disabled={!!draft}>{C.ADD_ROW}</Button>
        {gap !== 0 && (
          <label className="imp-confirm__choice">
            <input type="checkbox" checked={anyway} onChange={(e) => void toggleAnyway(e.target.checked)} />{C.IMPORT_ANYWAY}
          </label>
        )}
        <Button onClick={() => void done()}>{C.DONE}</Button>
      </div>
    </section>
  );
}
