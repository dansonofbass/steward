import { useEffect, useRef, useState, type RefObject } from 'react';
import { dollars } from '../../../lib/format';
import { withCelebrate } from '../../../lib/celebrations';
import { firstMaxed } from '../joy';
import type { Contributed, InvestmentPage, LimitLine } from './api';
import { CONTRIBUTIONS_TITLE, EMPLOYER_MATCH, ESTIMATED, FROM_PAY, MAXED_CHEER, MISSING, NOT_COUNTED, ROLLOVERS_IN, YOUR_CONTRIBUTIONS } from './copy';
import { limitAmount, limitSentence } from './format';

const fromNote = (from: Contributed['you_from'] | Contributed['match_from']) =>
  from === 'estimate' ? <span className="muted"> {ESTIMATED}</span> : from === 'payroll' ? <span className="muted"> {FROM_PAY}</span> : null;

/** A limit line: what went in of the year's limit, in bold, then on pace, maxed or missing. */
export function LimitText({ line }: { line: LimitLine }) {
  if (line.limit_cents === null) return <p className="inv-limit">{MISSING}</p>;
  return <p className="inv-limit"><strong>{limitAmount(line)}</strong> {limitSentence(line)}</p>;
}

/** "Maxed your 401(k) for 2026." the first time this device sees the limit reached (spec, Joy): the cheer is copy and
 *  always shows; the burst only while celebrations are on. */
export function useMaxedCheer(line: LimitLine | null): { ref: RefObject<HTMLElement | null>; cheer: string | null } {
  const ref = useRef<HTMLElement | null>(null);
  const [cheer, setCheer] = useState<string | null>(null);
  const key = line?.maxed && line.limit_cents !== null ? `${line.owner}:${line.kind}:${line.year}` : null;
  useEffect(() => {
    if (!key || !line || !firstMaxed(key)) return;
    setCheer(MAXED_CHEER.replace('{kind}', line.label).replace('{year}', String(line.year)));
    const el = ref.current;
    if (el) void withCelebrate((c) => { c.burst({ over: el }); });
  }, [key, line]);
  return { ref, cheer };
}

/** Contributions this year (investment views spec): yours (from the account's deposits or the pay facts), the match,
 *  rollovers (shown, never counted toward a limit), and the year's limit with "on pace". */
export function ContributionsSection({ data }: { data: NonNullable<InvestmentPage['contributions']> }) {
  const c = data.this_year;
  const { ref, cheer } = useMaxedCheer(data.missing ? null : data.line);
  return (
    <section className="inv-sec" aria-labelledby="inv-con-h" ref={ref}>
      <h2 id="inv-con-h">{CONTRIBUTIONS_TITLE}</h2>
      <dl className="inv-con">
        <div><dt>{YOUR_CONTRIBUTIONS}</dt><dd>{dollars(c.you_cents)}{fromNote(c.you_from)}</dd></div>
        {c.match_cents > 0 && <div><dt>{EMPLOYER_MATCH}</dt><dd>{dollars(c.match_cents)}{fromNote(c.match_from)}</dd></div>}
        {c.rollover_cents > 0 && <div><dt>{ROLLOVERS_IN}</dt><dd>{dollars(c.rollover_cents)} <span className="muted">{NOT_COUNTED}</span></dd></div>}
      </dl>
      {data.missing ? <p className="inv-limit">{MISSING}</p> : data.line && <LimitText line={data.line} />}
      {cheer && <p className="inv-cheer">{cheer}</p>}
    </section>
  );
}
