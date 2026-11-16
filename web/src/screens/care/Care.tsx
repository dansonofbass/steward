import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { aboutFor } from '../../ask/about';
import { useBook, useCanEdit } from '../../book/BookContext';
import { TRY_AGAIN } from '../../lib/copy';
import { useRemoval } from '../../lib/useRemoval';
import { AskAbout } from '../../ui/AskAbout';
import { Button } from '../../ui/Button';
import { Card } from '../../ui/Card';
import { Notice } from '../../ui/Notice';
import { RemovalLine } from '../../ui/RemovalLine';
import { Skeleton } from '../../ui/Skeleton';
import { failure } from '../settings/shared';
import { careKey, removeScenario, useCare, type CareCost, type CareScenario } from './api';
import * as C from './copy';
import { CostsCard } from './CostsCard';
import { QuoteSheet } from './QuoteSheet';
import { ScenarioCard } from './ScenarioCard';
import { ScenarioSheet } from './ScenarioSheet';
import { MonthByMonth } from './MonthByMonth';
import { HowItWorks, MediCalCard } from './Sections';
import { SetupCard } from './SetupCard';
import './care.css';

/** The inline ask before a scenario goes (T3). Focus goes to its Keep when it opens, since the Remove that opened it
 *  is gone from the page. */
function InlineAsk({ line, label, onRemove, onKeep }: { line: string; label: string; onRemove: () => void; onKeep: () => void }) {
  const keep = useRef<HTMLButtonElement>(null);
  useEffect(() => { keep.current?.focus(); }, []);
  return (
    <div className="care-actions" role="group" aria-label={line}>
      <span className="small">{line}</span>
      <Button variant="danger" aria-label={C.fill(C.REMOVE_NAMED, { label })} onClick={onRemove}>{C.REMOVE}</Button>
      <Button ref={keep} variant="quiet" onClick={onKeep}>{C.KEEP}</Button>
    </div>
  );
}

export default function Care() {
  const q = useCare();
  const qc = useQueryClient();
  const canEdit = useCanEdit();
  const chat = useBook()?.chat === true;
  const [editingSetup, setEditingSetup] = useState(false);
  const [sheet, setSheet] = useState<{ open: boolean; scenario: CareScenario | null }>({ open: false, scenario: null });
  const [quote, setQuote] = useState<CareCost | null>(null);
  const [removing, setRemoving] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  // A removed scenario or quote says so (THO-1). The scenario's card goes, so focus moves to the Scenarios heading; Keep
  // gives it back to the scenario's own Remove.
  const removal = useRemoval();
  const quoteLine = useRemoval();
  const kept = useRef<number | null>(null);
  if (q.isError) {
    return <div className="screen care"><Notice tone="error"><p>{q.error.message}</p><Button variant="quiet" onClick={() => void q.refetch()}>{TRY_AGAIN}</Button></Notice></div>;
  }
  if (!q.data) return <div className="screen care" aria-busy="true"><Skeleton lines={6} /></div>;
  const d = q.data;
  const full = d.scenarios.length >= d.max_scenarios;

  async function remove(s: CareScenario) {
    setError(null);
    removal.clear();
    try {
      qc.setQueryData(careKey, await removeScenario(s.id));
      removal.removedHere(C.fill(C.SCENARIO_REMOVED, { label: s.label }));
      setRemoving(null);
    } catch (err) {
      setError(failure(err));
    }
  }

  // Ask about this (P17): each scenario by its id; its number and level go, never its wording. Viewers can ask too.
  const ask = (s: CareScenario) => <AskAbout about={aboutFor.scenario(s)} surface={{ kind: 'care-scenario' }} thing={s.label} />;
  const actions = (s: CareScenario) => {
    if (!canEdit) return chat ? <div className="care-actions">{ask(s)}</div> : undefined;
    if (removing === s.id) {
      return <InlineAsk line={C.fill(C.REMOVE_ASK, { label: s.label })} label={s.label} onRemove={() => void remove(s)}
        onKeep={() => { kept.current = s.id; setRemoving(null); }} />;
    }
    return (
      <div className="care-actions">
        {ask(s)}
        <Button variant="quiet" aria-label={`${C.CHANGE} ${s.label}`} onClick={() => setSheet({ open: true, scenario: s })}>{C.CHANGE}</Button>
        <Button variant="quiet" aria-label={C.fill(C.REMOVE_NAMED, { label: s.label })} onClick={() => { removal.clear(); setRemoving(s.id); }}
          ref={(el) => { if (el && kept.current === s.id) { kept.current = null; el.focus(); } }}>{C.REMOVE}</Button>
      </div>
    );
  };

  return (
    <div className="screen care">
      <div className="care-head">
        <h1>{C.CARE}</h1>
        <AskAbout about={aboutFor.care()} surface={{ kind: 'care' }} thing={C.CARE} />
      </div>
      {d.setup && d.age !== null && <p className="muted">{C.fill(C.FOR, { name: d.setup.person_label, age: String(d.age) })}</p>}
      {!d.set_up || editingSetup ? (
        canEdit ? <SetupCard data={d} onDone={() => setEditingSetup(false)} /> : <Card><p>{C.NOT_SET_UP}</p></Card>
      ) : (
        <>
          <section className="stack" aria-labelledby="care-scenarios">
            <h2 id="care-scenarios" ref={removal.anchor} tabIndex={-1}>{C.SCENARIOS}</h2>
            <RemovalLine removal={removal} />
            {error && <Notice tone="error">{error}</Notice>}
            {d.spending && d.spending.months === 0 && !d.spending.typed && (
              <Notice tone="warn">
                <p>{C.NO_SPENDING}</p>
                {canEdit && <Button variant="quiet" onClick={() => setEditingSetup(true)}>{C.CHANGE_SETUP}</Button>}
              </Notice>
            )}
            <ul className="care-grid">{d.scenarios.map((s) => <li key={s.id}><ScenarioCard s={s} actions={actions(s)} /></li>)}</ul>
            {canEdit && (
              <div className="stack">
                <Button variant="quiet" disabled={full} onClick={() => setSheet({ open: true, scenario: null })}>{C.ADD}</Button>
                {full && <p className="small muted">{C.fill(C.MAX, { n: String(d.max_scenarios) })}</p>}
              </div>
            )}
          </section>
          {d.medi_cal && <MediCalCard m={d.medi_cal} />}
          <CostsCard costs={d.costs} onQuote={canEdit ? (c) => { quoteLine.clear(); setQuote(c); } : undefined} />
          <RemovalLine removal={quoteLine} />
          <HowItWorks lines={d.how} notes={d.notes} onChangeSetup={canEdit ? () => setEditingSetup(true) : undefined} />
        </>
      )}
      <MonthByMonth m={d.monthly} />
      <ScenarioSheet open={sheet.open} scenario={sheet.scenario} data={d} onClose={() => setSheet({ open: false, scenario: null })} />
      <QuoteSheet cost={quote} onClose={() => setQuote(null)} onRemoved={(label) => quoteLine.say(C.fill(C.QUOTE_REMOVED, { label: label.toLowerCase() }))} />
    </div>
  );
}
