import { useRef, useState } from 'react';
import { Link } from '../../book/links';
import { Button } from '../../ui/Button';
import { ConfirmSheet } from '../../ui/ConfirmSheet';
import type { ReadyRow } from './api';
import { CHECK_AGAIN, FASTER_WITH_GPU, GPU_GUIDE, PAIR, PAIR_AGAIN, PAIR_AGAIN_BODY, PAIR_AGAIN_Q, RUNS_ON, TURN_ON } from './copy';
import { PairForm } from './PairForm';
import { SettingLine } from './SettingLine';

/** Ask, in the order a person needs it: the line that names the gateway, the pairing code, the Claude key line, Check again when the gateway is away, Pair again, Turn on. */
export function GatewayPanel({ row, onCheck, checking }: { row: ReadyRow; onCheck: () => void; checking: boolean }) {
  const [checked, setChecked] = useState(false);
  const [asking, setAsking] = useState(false);
  const [pairing, setPairing] = useState(false);
  // Pair again takes its own button away and opens the pairing form, so focus goes to the form's code box.
  const pairBox = useRef<HTMLDivElement>(null);
  const toPairForm = () => pairBox.current?.querySelector<HTMLElement>('input') ?? null;
  const { url_set, paired, state, chat_on, accelerator } = row.extra as { url_set?: boolean; paired?: boolean; state?: string | null; chat_on?: boolean; accelerator?: string | null };
  const runsOn = typeof accelerator === 'string' && Object.hasOwn(RUNS_ON, accelerator) ? (accelerator as keyof typeof RUNS_ON) : null;
  const lines = row.lines.map((l) => (
    <SettingLine key={l.name} line={l} done={row.status === 'done'} checked={checked} checking={checking} onCheck={() => { setChecked(true); onCheck(); }} />
  ));
  return (
    <div className="stack stack--tight">
      {!url_set && lines}
      {url_set && (pairing || !paired) && <div ref={pairBox}><PairForm onPaired={() => setPairing(true)} /></div>}
      {paired && state === 'not_set_up' && lines}
      {paired && state !== 'ok' && state !== 'not_set_up' && (
        <div className="ready__check"><Button variant="quiet" busy={checking} onClick={onCheck}>{CHECK_AGAIN}</Button></div>
      )}
      {paired && state === 'ok' && runsOn && (
        <p className="ready__runs">{RUNS_ON[runsOn]}{runsOn === 'cpu' && <> <a className="link" href={GPU_GUIDE} target="_blank" rel="noreferrer">{FASTER_WITH_GPU}</a></>}</p>
      )}
      {paired && !pairing && <div><Button variant="quiet" onClick={() => setAsking(true)}>{PAIR_AGAIN}</Button></div>}
      {chat_on === false && <p><Link className="link" to="/settings/chat">{TURN_ON}</Link></p>}
      <ConfirmSheet open={asking} title={PAIR_AGAIN_Q} body={PAIR_AGAIN_BODY} action={PAIR} variant="primary"
        onConfirm={() => { setAsking(false); setPairing(true); }} onClose={() => setAsking(false)} returnTo={toPairForm} />
    </div>
  );
}
