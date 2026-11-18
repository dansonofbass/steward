import type { SinceData } from '../../api/home';
import { nothingNew, SINCE_HEAD, whenWord } from './sinceWhen';

// Issue #24: the month strip and Since you last looked are their own chunks. Until a chunk lands, its place on Home is
// held by a room of its own shape and classes (home.css holds the layout both share), so For you and the accounts
// never move down when it arrives. Hidden from assistive technology: the real part says it all when it lands.
//
// A line the room can't fill yet holds a no-break space (BLANK), never a plain one: a line of plain spaces, or an empty
// flex box, has no height at all (rooms.test.tsx).
export const BLANK = '\u00a0';

/** The strip's room: its padding, the 36 px chart and one line of month names. */
export function StripRoom() {
  return (
    <div className="mstrip" aria-hidden="true" data-testid="strip-room">
      <span className="strip" />
      <span className="mstrip__foot"><span>{BLANK}</span></span>
    </div>
  );
}

/** Since's room: the card, the same heading (its when word too, so it wraps where the real one does), and one row for
 *  each line HomeSince will show, from the same /api/home data. */
export function SinceRoom({ since, asOf }: { since: SinceData; asOf: string }) {
  const rows = since.lines.length + (since.net_worth_cents === null ? 0 : 1);
  const when = whenWord(since.from_day, asOf, since.over_month);
  return (
    <section className="card since" aria-hidden="true" data-testid="since-room">
      <p className="since__head">
        {SINCE_HEAD}
        {rows > 0 && <>{' '}<span className="since__when muted">({when})</span></>}
      </p>
      {rows === 0 ? <p className="muted">{nothingNew(when)}</p> : (
        <ul className="since__list">
          {Array.from({ length: rows }, (_, i) => <li key={i} className="since__row"><span>{BLANK}</span></li>)}
        </ul>
      )}
      {since.more > 0 && <p className="since__more small">{BLANK}</p>}
    </section>
  );
}
