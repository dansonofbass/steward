import type { Removal } from '../lib/useRemoval';
import './RemovalLine.css';

/** The line after a removal ("Removed Vee from Mom."). The live region is always in the page, so a screen reader hears
 *  the line when it fills in (a region added with its text already in it is often not read). `holdsFocus` makes the
 *  line the place focus lands, for a list that can vanish with its last row. Each line is a new <p> (keyed on seq), so
 *  the same line said twice still changes the region and is heard twice. */
export function RemovalLine({ removal, holdsFocus = false }: { removal: Removal; holdsFocus?: boolean }) {
  return (
    <div aria-live="polite" aria-atomic="true" className="removal-line" ref={holdsFocus ? removal.anchor : undefined} tabIndex={holdsFocus ? -1 : undefined}>
      {removal.line && <p key={removal.seq} className="notice notice--info">{removal.line}</p>}
    </div>
  );
}
