/** Four chips (P6): the guess first, then the household's top categories, so keys 1–4 cover them all. */
export const chipsFor = (guess: string | null, top: readonly string[]): string[] =>
  (guess ? [guess, ...top.filter((c) => c !== guess)] : [...top]).slice(0, 4);

/** Review focus, Keyboard: what a key does on the current card. Z (Undo) is Review's, in both views. */
export type KeyAct =
  | { type: 'take' } | { type: 'chip'; index: number } | { type: 'more' }
  | { type: 'snooze' } | { type: 'ignore' } | { type: 'business' } | { type: 'note' };

export function keyAct(key: string, chipCount: number): KeyAct | null {
  if (key === 'Enter') return { type: 'take' };
  if (/^[1-4]$/.test(key)) {
    const index = Number(key) - 1;
    return index < chipCount ? { type: 'chip', index } : null;
  }
  switch (key.toLowerCase()) {
    case '/': return { type: 'more' };
    case 's': return { type: 'snooze' };
    case 'i': return { type: 'ignore' };
    case 'b': return { type: 'business' };
    case 'n': return { type: 'note' };
    default: return null;
  }
}
