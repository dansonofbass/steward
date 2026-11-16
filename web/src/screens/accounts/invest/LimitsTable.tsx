import type { RefObject } from 'react';
import { dollars } from '../../../lib/format';
import { Notice } from '../../../ui/Notice';
import { Skeleton } from '../../../ui/Skeleton';
import { useLimits, type LimitLine } from './api';
import { ESTIMATED, LIMITS_TITLE, MISSING, ROW_LABEL } from './copy';
import { useMaxedCheer } from './Contributions';
import { limitAmount, limitSentence } from './format';
import './invest.css';

/** One person's (or the household's) line: the kind and whose, what went in of the limit, and on pace. */
export function LimitRow({ line, missing }: { line: LimitLine; missing: boolean }) {
  const { ref, cheer } = useMaxedCheer(missing ? null : line);
  return (
    <div className="limits-row" ref={ref as RefObject<HTMLDivElement | null>}>
      <strong>{line.owner === 'household' ? line.label : ROW_LABEL.replace('{label}', line.label).replace('{name}', line.name)}</strong>
      <span>{missing || line.limit_cents === null ? dollars(line.in_cents) : limitAmount(line)}</span>
      {!missing && line.limit_cents !== null && <p>{limitSentence(line)}</p>}
      {line.estimated && <p>{ESTIMATED}</p>}
      {cheer && <p className="inv-cheer">{cheer}</p>}
    </div>
  );
}

/** This year's limits, filled per person, once on Accounts (investment views spec), in its own chunk. Nothing shows
 *  when the household has no retirement account with a limit. */
export default function LimitsTable() {
  const q = useLimits();
  if (q.isPending) return <Skeleton lines={3} />;
  if (q.isError) return <Notice tone="error"><p>{q.error.message}</p></Notice>;
  const { year, missing, lines } = q.data;
  if (lines.length === 0) return null;
  return (
    <section className="acct-sec" aria-labelledby="limits-h">
      <h2 id="limits-h">{LIMITS_TITLE.replace('{year}', String(year))}</h2>
      {missing && <p className="muted">{MISSING}</p>}
      <div className="card limits-table">
        {lines.map((l) => <LimitRow key={`${l.owner}-${l.kind}`} line={l} missing={missing} />)}
      </div>
    </section>
  );
}
