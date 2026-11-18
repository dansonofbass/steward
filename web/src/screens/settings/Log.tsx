import { CircleAlert, Info, TriangleAlert, type LucideIcon } from 'lucide-react';
import { useState } from 'react';
import { useEvents } from '../../api/hooks';
import { dateLabelFromIso } from '../../lib/format';
import { clockTime } from '../../lib/today';
import { NOTHING_HERE_YET, S_LOG, UNRESOLVED_ONLY } from '../../lib/copy';
import { Card } from '../../ui/Card';
import { IconLabel } from '../../ui/IconLabel';
import { Notice } from '../../ui/Notice';
import { Skeleton } from '../../ui/Skeleton';

const LEVELS: Record<string, { icon: LucideIcon; label: string }> = {
  info: { icon: Info, label: 'Info' },
  warn: { icon: TriangleAlert, label: 'Warning' },
  error: { icon: CircleAlert, label: 'Error' },
};

export default function Log() {
  const [unresolved, setUnresolved] = useState(false);
  const events = useEvents(unresolved);
  const today = new Date();
  return (
    <section className="spage" aria-labelledby="log-h">
      <h2 id="log-h">{S_LOG}</h2>
      <label className="check-row">
        <input type="checkbox" checked={unresolved} onChange={(e) => setUnresolved(e.target.checked)} />
        <span>{UNRESOLVED_ONLY}</span>
      </label>
      {events.isPending && <Card><Skeleton lines={4} /></Card>}
      {events.isError && <Notice tone="error">{events.error.message}</Notice>}
      {events.isSuccess && events.data.events.length === 0 && <p className="muted">{NOTHING_HERE_YET}</p>}
      {events.isSuccess && events.data.events.length > 0 && (
        <Card className="lines">
          <ul className="plain">
            {events.data.events.map((e) => {
              const lvl = LEVELS[e.level] ?? LEVELS.info;
              return (
                <li className="line" key={e.id}>
                  <div className="line__main">
                    <span>{e.message}</span>
                    <span className="small muted">{dateLabelFromIso(e.at, today)} · {clockTime(e.at)}</span>
                    {e.resolved_at && <span className="small muted">Resolved {dateLabelFromIso(e.resolved_at, today)}</span>}
                  </div>
                  <span className="small"><IconLabel icon={lvl.icon} label={lvl.label} /></span>
                </li>
              );
            })}
          </ul>
        </Card>
      )}
    </section>
  );
}
