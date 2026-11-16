import { UNDO } from '../../lib/copy';
import type { Part } from '../../lib/receipt';
import { Button } from '../../ui/Button';
import { Rich } from '../../ui/Rich';

export type Said = { parts: Part[]; cheer: string | null; undo: string | null; error?: boolean };

/** What an answer did, in plain words, with Undo while it can (JR: nothing vanishes unseen, always Undo). */
export function SaidLine({ said, busy, onUndo }: { said: Said; busy: boolean; onUndo: () => void }) {
  return (
    <div className="same__said" role={said.error ? 'alert' : 'status'}>
      {said.cheer && <strong className="same__cheer">{said.cheer}</strong>}
      <p><Rich parts={said.parts} /></p>
      {said.undo && <Button variant="quiet" busy={busy} onClick={onUndo}>{UNDO}</Button>}
    </div>
  );
}
