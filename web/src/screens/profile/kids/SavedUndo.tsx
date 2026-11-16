import { UNDO } from '../../../lib/copy';
import { SAVED } from '../copy';

/** "Saved · Undo" after a kid's edit (spec, The card). */
export function SavedUndo({ show, onUndo }: { show: boolean; onUndo: () => void }) {
  if (!show) return null;
  return <p className="prof-saved" role="status">{SAVED} · <button type="button" className="link" onClick={onUndo}>{UNDO}</button></p>;
}
