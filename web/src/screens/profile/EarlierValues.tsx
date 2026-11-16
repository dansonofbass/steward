import { useQueries } from '@tanstack/react-query';
import { Notice } from '../../ui/Notice';
import { Sheet } from '../../ui/Sheet';
import { Skeleton } from '../../ui/Skeleton';
import { factHistory } from './api';
import { EARLIER_VALUES, NO_EARLIER } from './copy';
import { historyLine, type FactField } from './history';

/** Fact history for the step open in Settings, newest first, read only when the sheet opens. */
export function EarlierValues({ open, onClose, fields }: { open: boolean; onClose: () => void; fields: FactField[] }) {
  const results = useQueries({
    queries: fields.map((f) => ({ queryKey: ['fact-history', f.key], queryFn: () => factHistory(f.key), enabled: open })),
  });
  const today = new Date();
  return (
    <Sheet open={open} onClose={onClose} title={EARLIER_VALUES}>
      <div className="stack">
        {fields.map((f, i) => {
          const r = results[i];
          return (
            <section key={f.key} className="ob-sec" aria-labelledby={`earlier-${i}`}>
              <h3 id={`earlier-${i}`} className="eyebrow">{f.label}</h3>
              {r.isError ? <Notice tone="error">{r.error.message}</Notice>
                : !r.data ? <Skeleton lines={2} />
                : r.data.history.length === 0 ? <p className="small muted">{NO_EARLIER}</p>
                : <ul className="plain">{r.data.history.map((h, j) => <li key={j} className="small">{historyLine(f.kind, h, today)}</li>)}</ul>}
            </section>
          );
        })}
      </div>
    </Sheet>
  );
}
