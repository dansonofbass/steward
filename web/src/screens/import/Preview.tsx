import type { RefObject } from 'react';
import { monthYear } from '../../lib/format';
import { Button } from '../../ui/Button';
import { Notice } from '../../ui/Notice';
import type { PreviewReply } from './api';
import * as C from './copy';
import type { LookLine } from './Look';
import { count, monthDay } from './logic';

type Props = {
  reply: PreviewReply; changed: boolean; busy: boolean; headingRef?: RefObject<HTMLHeadingElement | null>;
  onImport: () => void; onBack: () => void; onLook: (line: LookLine) => void;
};

const ym = (iso: string) => monthYear(Number(iso.slice(0, 4)), Number(iso.slice(5, 7)));
function covers(from: string, to: string) {
  return from.slice(0, 7) === to.slice(0, 7) ? ym(to) : `${ym(from)} – ${ym(to)}`;
}

/** Step 2 (P4): one preview for the whole batch, a dl, each Look a button named for its line. */
export function Preview({ reply, changed, busy, headingRef, onImport, onBack, onLook }: Props) {
  const look = (line: LookLine, label: string) => (
    <button type="button" className="link" aria-label={C.LOOK_ON.replace('{line}', label)} onClick={() => onLook(line)}>{C.LOOK}</button>
  );
  const writes = reply.writes ?? reply.new;
  const sfLabel = reply.simplefin.since ? C.SIMPLEFIN_AFTER.replace('{date}', monthDay(reply.simplefin.since)) : C.SIMPLEFIN;
  const bal = reply.balances;
  const balLabel = bal && (bal.kept ? C.BALANCES_KEPT.replace('{k}', count(bal.kept)) : C.BALANCES).replace('{n}', count(bal.n));
  const hold = reply.holdings;
  const holdLabel = hold && (hold.n === 1 ? C.PV_HOLDINGS_ONE : C.PV_HOLDINGS.replace('{n}', count(hold.n)));
  const keptHoldings = (hold?.rows ?? []).filter((h) => h.kept).map((h) => C.KEPT_HOLDINGS.replace('{date}', monthDay(h.as_of)));
  const kept = (bal?.rows ?? []).filter((b) => b.kept).map((b) => C.KEPT_BALANCE.replace('{date}', monthDay(b.as_of)));
  const notes = [...kept, ...keptHoldings, ...reply.files.flatMap((f) => [
    ...(f.held ? [`${f.name} · ${f.held}`] : f.errors.map((e) => `${f.name} · ${e.text}`)),
    ...(!f.held && f.unreadable > f.errors.length ? [`${f.name} · ${C.MORE_ERRORS.replace('{n}', count(f.unreadable - f.errors.length))}`] : []),
    ...(Object.entries(f.left_out) as [keyof typeof C.LEFT_OUT, number][]).filter(([, n]) => n > 0)
      .map(([k, n]) => `${f.name} · ${(n === 1 ? C.LEFT_OUT[k][0] : C.LEFT_OUT[k][1]).replace('{n}', count(n))}`),
  ])];
  return (
    <section className="imp-pv-step" aria-labelledby="pv-h">
      <h3 id="pv-h" className="subhead" tabIndex={-1} ref={headingRef}>{C.STEP_TWO}</h3>
      {changed && <Notice tone="warn">{C.CHANGED}</Notice>}
      <dl className="imp-pv">
        <div><dt>{C.NEW}</dt><dd>{count(reply.new)}</dd></div>
        {reply.already > 0 && <div><dt>{C.ALREADY}</dt><dd>{count(reply.already)} · {look('already', C.ALREADY)}</dd></div>}
        {reply.simplefin.n > 0 && <div><dt>{sfLabel}</dt><dd>{C.SKIPPED.replace('{n}', count(reply.simplefin.n))} · {look('simplefin', sfLabel)}</dd></div>}
        {reply.same > 0 && <div><dt>{C.SAME}</dt><dd>{count(reply.same)} · {look('same', C.SAME)}</dd></div>}
        {bal && bal.n > 0 && <div><dt>{balLabel}</dt><dd>{count(bal.n)} · {look('balances', balLabel!)}</dd></div>}
        {hold && hold.n > 0 && <div><dt>{holdLabel}</dt><dd>{look('holdings', holdLabel!)}</dd></div>}
        {reply.from && reply.to && <div><dt>{C.COVERS}</dt><dd>{covers(reply.from, reply.to)}</dd></div>}
      </dl>
      {notes.length > 0 && <ul className="plain imp-pv__notes">{notes.map((n) => <li key={n}>{n}</li>)}</ul>}
      <div className="row-actions">
        <Button busy={busy} disabled={writes === 0} onClick={onImport}>{C.IMPORT_N.replace('{n}', count(writes))}</Button>
        <Button variant="quiet" disabled={busy} onClick={onBack}>{C.BACK}</Button>
      </div>
    </section>
  );
}
