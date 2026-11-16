import { Button } from '../../ui/Button';
import { Card } from '../../ui/Card';
import type { CareCost } from './api';
import * as C from './copy';

/** Each care cost with its source and year, or the family's quote (spec 4.2). Managers get onQuote. */
export function CostsCard({ costs, onQuote }: { costs: CareCost[]; onQuote?: (c: CareCost) => void }) {
  return (
    <Card className="stack">
      <h2>{C.COSTS}</h2>
      <ul className="care-costs">
        {costs.map((c) => {
          const action = c.quote ? C.CHANGE_QUOTE : C.ENTER_QUOTE;
          return (
            <li key={c.key}>
              <span className="care-costs__head"><span>{c.label}</span><span className="money">{c.text}</span></span>
              <span className="small muted">{c.line}</span>
              {onQuote && <Button variant="quiet" aria-label={C.fill(C.QUOTE_FOR, { action, label: c.label })} onClick={() => onQuote(c)}>{action}</Button>}
            </li>
          );
        })}
      </ul>
    </Card>
  );
}
