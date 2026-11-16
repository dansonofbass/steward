import { Check, X } from 'lucide-react';

/** A check's two wordings: what the line says when it passed, and when it failed. */
export type CheckWords = readonly [passed: string, failed: string];

/** One line of a list of checks. The tick or cross is hidden from a screen reader, so the words carry the state: a
 *  failed check says it failed, and what a screen reader hears matches what the eye sees (gate finding THO-2). */
export function CheckLine({ ok, words }: { ok: boolean; words: CheckWords }) {
  const Icon = ok ? Check : X;
  return <li className={ok ? 'is-on' : 'is-off'}><Icon size={20} aria-hidden="true" />{ok ? words[0] : words[1]}</li>;
}
