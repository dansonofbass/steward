import { Button } from '../../ui/Button';
import { Card } from '../../ui/Card';
import type { CareOut } from './api';
import * as C from './copy';

export function MediCalCard({ m }: { m: NonNullable<CareOut['medi_cal']> }) {
  return (
    <Card className="stack">
      <h2>{C.MEDI_CAL}</h2>
      <p>{m.rule_line}</p>
      {m.url && <a className="link" href={m.url} target="_blank" rel="noreferrer">{C.READ_RULE}</a>}
      <p className="small">{m.disclaimer}</p>
      <h3 className="eyebrow">{C.TOPICS}</h3>
      <ul className="small care-list">{m.topics.map((t) => <li key={t}>{t}</li>)}</ul>
    </Card>
  );
}

export function HowItWorks({ lines, notes, onChangeSetup }: { lines: string[]; notes: string[]; onChangeSetup?: () => void }) {
  return (
    <section className="stack" aria-labelledby="care-how">
      <h2 id="care-how">{C.HOW}</h2>
      <ul className="small muted care-list">{[...lines, ...notes].map((l) => <li key={l}>{l}</li>)}</ul>
      {onChangeSetup && <Button variant="quiet" onClick={onChangeSetup}>{C.CHANGE_SETUP}</Button>}
    </section>
  );
}
