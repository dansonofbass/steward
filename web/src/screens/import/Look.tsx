import { useState } from 'react';
import { dateLabel, money } from '../../lib/format';
import { Button } from '../../ui/Button';
import { Sheet } from '../../ui/Sheet';
import type { PreviewReply } from './api';
import * as C from './copy';
import { count, monthDay } from './logic';

export type LookLine = 'same' | 'simplefin' | 'already' | 'balances' | 'holdings';
type Props = {
  line: LookLine; reply: PreviewReply; include: Record<string, number[]>; simplefinOn: boolean;
  onDone: (include: Record<string, number[]>, simplefinOn: boolean) => void; onClose: () => void;
};

// A file's rows are history, so the date always carries its year ("Mar 1, 2024"): today is given as a day in 2000.
const ALWAYS_YEAR = '2000-01-01';
const said = (r: { posted_at: string; description: string; amount_cents: number }) =>
  `${dateLabel(r.posted_at, ALWAYS_YEAR)} · ${r.description} · ${money(r.amount_cents)}`;
const shown = (more: number) => (more > 0 ? C.NOT_SHOWN.replace('{n}', count(more)) : null);

/** A sheet over Preview listing one line's rows (P15, P16), at most 200; nothing vanishes unseen. Done sends the
 *  choices back and the preview reloads. */
export function Look({ line, reply, include, simplefinOn, onDone, onClose }: Props) {
  const [chosen, setChosen] = useState(include);
  const [on, setOn] = useState(simplefinOn);
  const toggle = (token: string, row: number, yes: boolean) => setChosen((c) => {
    const rows = new Set(c[token] ?? []);
    if (yes) rows.add(row); else rows.delete(row);
    return { ...c, [token]: [...rows].sort((a, b) => a - b) };
  });
  return (
    <Sheet open onClose={onClose} title={C.LOOK_TITLES[line]}>
      <div className="imp-look">
        {line === 'same' && (
          <ul className="plain imp-look__rows">
            {reply.look.same.map((r) => (
              <li key={`${r.token}-${r.row}`}>
                <p>{C.IN_FILE}: {said(r)}</p>
                <p className="muted">{r.match.where === 'steward' ? C.IN_STEWARD : C.EARLIER}: {said(r.match)}</p>
                <label className="check-row">
                  <input className="check" type="checkbox" checked={(chosen[r.token] ?? []).includes(r.row)}
                    onChange={(e) => toggle(r.token, r.row, e.target.checked)} />
                  <span>{C.IMPORT_ANYWAY}</span>
                </label>
              </li>
            ))}
            {shown(reply.look.same_more) && <li className="muted">{shown(reply.look.same_more)}</li>}
          </ul>
        )}
        {line === 'simplefin' && (
          <>
            <label className="check-row">
              <input type="checkbox" role="switch" checked={on} onChange={(e) => setOn(e.target.checked)} />
              <span>{C.IMPORT_TOO}</span>
            </label>
            {reply.look.simplefin.map((g) => (
              <section key={g.account_id} className="imp-look__group">
                <h4 className="small">{g.account}</h4>
                <p className="small muted">{C.HAS_FROM.replace('{date}', monthDay(g.since))}</p>
                <ul className="plain imp-look__rows">{g.rows.map((r) => <li key={`${r.token}-${r.row}`}>{said(r)}</li>)}</ul>
                {shown(g.more) && <p className="muted">{shown(g.more)}</p>}
              </section>
            ))}
          </>
        )}
        {line === 'already' && (
          <ul className="plain imp-look__rows">
            {reply.look.already.map((r) => <li key={`${r.token}-${r.row}`}>{said(r)}</li>)}
            {shown(reply.look.already_more) && <li className="muted">{shown(reply.look.already_more)}</li>}
          </ul>
        )}
        {line === 'balances' && (
          <ul className="plain imp-look__rows">
            {(reply.balances?.rows ?? []).map((b) => (
              <li key={`${b.account}-${b.as_of}`}>
                {b.account} · {dateLabel(b.as_of, ALWAYS_YEAR)} · {money(b.cents)}{b.kept ? ` · ${C.KEPT}` : ''}
              </li>
            ))}
          </ul>
        )}
        {line === 'holdings' && (
          <ul className="plain imp-look__rows">
            {(reply.holdings?.rows ?? []).map((h) => (
              <li key={`${h.account}-${h.as_of}`}>
                {C.HOLDINGS_LINE.replace('{account}', h.account).replace('{date}', dateLabel(h.as_of, ALWAYS_YEAR)).replace('{holdings}', h.count === 1 ? C.HOLDINGS_ONE : C.HOLDINGS_N.replace('{n}', count(h.count)))}
                {h.kept ? ` · ${C.KEPT}` : ''}
              </li>
            ))}
          </ul>
        )}
        <Button onClick={() => onDone(line === 'same' ? chosen : include, line === 'simplefin' ? on : simplefinOn)}>{C.DONE}</Button>
      </div>
    </Sheet>
  );
}
