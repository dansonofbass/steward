import { Tip } from '../../ui/Tip';
import type { PlanResult } from './api';
import { COMFORTABLY_AT, IN_YEAR, LIKELY_AT, NOT_BY_70, TIP_COMFORTABLY, TIP_LIKELY, WAS } from './copy';

type AgeProps = { testId: string; className?: string; label: string; tip: string; age: number | null; year: number | null; was?: number | null };

function Age({ testId, className = '', label, tip, age, year, was }: AgeProps) {
  const changed = was !== undefined && was !== age;
  return (
    <div className={`age ${className}`} data-testid={testId}>
      <span className="age__label">{label}<Tip>{tip}</Tip></span>
      {age === null ? <span className="age__n age__n--none">{NOT_BY_70}</span> : <span className="age__n">{age}</span>}
      {age !== null && year !== null && <span className="age__year">{IN_YEAR.replace('{year}', String(year))}</span>}
      {changed && <span className="age__was">{WAS.replace('{age}', was === null ? NOT_BY_70.toLowerCase() : String(was))}</span>}
    </div>
  );
}

type Props = { result: PlanResult; was?: PlanResult | null; pending?: boolean; younger: string };

/** "Comfortably at 63 · Likely at 60". `was` is the saved plan's answer while a lever is moved. */
export function Ages({ result, was, pending = false, younger }: Props) {
  return (
    <div className={`ages${pending ? ' is-pending' : ''}`} aria-busy={pending || undefined} aria-live="polite">
      <Age testId="age-comfortable" label={COMFORTABLY_AT} age={result.comfortable_age} year={result.comfortable_year}
        tip={TIP_COMFORTABLY.replace('{younger}', younger)} was={was ? was.comfortable_age : undefined} />
      <Age testId="age-likely" className="age--likely" label={LIKELY_AT} age={result.likely_age} year={result.likely_year}
        tip={TIP_LIKELY.replace('{younger}', younger)} was={was ? was.likely_age : undefined} />
    </div>
  );
}
