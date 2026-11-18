import { useEffect, useRef, useState } from 'react';
import { withCelebrate } from '../../lib/celebrations';
import { drawFrom } from '../../lib/lines';
import type { PlanReady } from './api';
import { baseOf, changeLine, closerOf, firstTimeFor } from './change';
import { CLOSER_CHEERS } from './copy';

/** What changed since the last saved plan, under the two ages (plan subpages). When the Comfortably age moved earlier by
 *  half a year or more, the first time this device sees that change: a cheer (copy, so it shows with celebrations off
 *  too) and a small burst from the line (only while celebrations are on). */
export function ChangeLine({ data, today = new Date() }: { data: PlanReady; today?: Date }) {
  const change = changeLine(data, today);
  const band = change ? closerOf(change) : null;
  const key = `${baseOf(data)?.id ?? 0}:${data.result.input_digest}`;
  const ref = useRef<HTMLParagraphElement>(null);
  const [cheer, setCheer] = useState<string | null>(null);
  useEffect(() => {
    if (!band || !firstTimeFor(key)) return;
    setCheer(drawFrom(`closer-${band}`, CLOSER_CHEERS[band]));
    const line = ref.current;
    if (line) void withCelebrate((c) => { c.closer({ over: line }); });
  }, [band, key]);
  if (!change) return null;
  return (
    <div className="change">
      <p ref={ref} className={`change__line is-${change.dir}`} data-testid="change-line">
        {change.dir !== 'same' && <span className="change__arrow" aria-hidden="true">{change.dir === 'earlier' ? '▼ ' : '▲ '}</span>}
        <span className="change__text">{change.text}</span>
      </p>
      {cheer && <p className="change__cheer" data-testid="change-cheer">{cheer}</p>}
    </div>
  );
}
