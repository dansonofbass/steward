import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { Txn } from '../../../api/types';
import { useIsHousehold } from '../../../book/BookContext';
import { label } from '../../../lib/categories';
import { SKIP_FOR_NOW } from '../../../lib/copy';
import { reducedMotion } from '../../../lib/celebrations';
import { demoState, setDemo, swipeOn } from '../../../lib/reviewPrefs';
import { useWide } from '../../../lib/useWide';
import { Button } from '../../../ui/Button';
import { FINE } from '../TopBar';
import type { ActKind, Done } from '../useReviewActions';
import * as C from './copy';
import { type CardRole, type Controls, FocusCard } from './FocusCard';
import { chipsFor } from './keymap';
import type { Leave } from './motion';
import { shouldNudge } from './useDemo';
import './focus.css';

type Props = {
  /** The queue as it stands, oldest first, without the rows that left this visit. */
  rows: readonly Txn[];
  chips: readonly string[];
  today: Date;
  /** A card Undo brought back (P15): it becomes the current card. A new seq each time. */
  back: { txn: Txn; seq: number } | null;
  onBegin: (txn: Txn, kind: ActKind) => string;
  onDone: (txn: Txn, entry: string, d: Done) => void;
  onFail: (entry: string) => void;
  onNote: (txn: Txn, token: string, text: string) => void;
  /** The chunk couldn't load (load.tsx's Missing calls it). */
  onMissing: () => void;
};

/** Review focus (decision 1): one card at a time, the next already behind it, and the buttons under the stage. The
 *  current card is pinned by id: a refetch never swaps it (P32). When a reply lands the next card is current at once and
 *  the acted card leaves on top (P8, engineering choice 1). The buttons persist across cards, so focus can stay on them
 *  (P30). */
export default function Focus({ rows, chips, today, back, onBegin, onDone, onFail, onNote }: Props) {
  const [pinned, setPinned] = useState<Txn | null>(rows[0] ?? null);
  const [leaving, setLeaving] = useState<{ txn: Txn; how: Leave } | null>(null);
  const [busy, setBusy] = useState(false);
  const [seenBack, setSeenBack] = useState<number | null>(back?.seq ?? null);   // a back from before this mount is old news
  const [undone, setUndone] = useState<{ id: number; seq: number } | null>(null);
  const [waitingFor, setWaitingFor] = useState<number | null>(null);   // a returned card, until a refetch lists it
  const controls = useRef<Controls | null>(null);
  const bar = useRef<HTMLDivElement>(null);
  const stage = useRef<HTMLDivElement>(null);
  const focusCard = useRef(false);
  const fine = useWide(FINE);
  const swipe = useMemo(swipeOn, []);
  const household = useIsHousehold();
  const coarse = useWide('(pointer: coarse)');
  const [hint, setHint] = useState(() => demoState() !== 'done');
  // The nudge plays on the first focus card only, once (P13).
  const [demoFor] = useState<number | null>(() =>
    (shouldNudge({ coarse, swipe: swipeOn(), reduced: reducedMotion(), state: demoState() }) ? rows[0]?.id ?? null : null));

  if (back && back.seq !== seenBack) {
    setSeenBack(back.seq);
    if (leaving?.txn.id === back.txn.id) setLeaving(null);    // undone while it was still leaving: one card, one key
    setPinned(back.txn);
    setUndone({ id: back.txn.id, seq: back.seq });
    setWaitingFor(back.txn.id);
    focusCard.current = true;
  }
  const live = pinned ? rows.find((r) => r.id === pinned.id) : undefined;
  if (waitingFor !== null && live) setWaitingFor(null);
  if (!pinned && rows[0]) setPinned(rows[0]);
  const current = pinned ? (live ?? pinned) : null;
  const elsewhere = pinned !== null && !live && waitingFor !== pinned.id;
  const next = rows.find((r) => r.id !== current?.id && r.id !== leaving?.txn.id) ?? null;

  const begin = useCallback((txn: Txn, kind: ActKind) => {
    setBusy(true);
    performance.mark('focus-tap');
    return onBegin(txn, kind);
  }, [onBegin]);
  const fail = useCallback((entry: string) => { setBusy(false); onFail(entry); }, [onFail]);
  const finish = (txn: Txn, entry: string, d: Done, how: Leave) => {
    setBusy(false);
    focusCard.current = !bar.current?.contains(document.activeElement);
    const gone = new Set([txn.id, ...(d.kind === 'sort' ? d.ids : [])]);
    setPinned(rows.find((r) => !gone.has(r.id)) ?? null);
    setLeaving({ txn, how });
    if (d.kind === 'sort' && hint) { setHint(false); setDemo('done'); }   // the first sort in focus ends the hint
    onDone(txn, entry, d);
    performance.mark('focus-next');
    performance.measure('focus-action', 'focus-tap', 'focus-next');
  };
  const moveNext = () => {
    focusCard.current = !bar.current?.contains(document.activeElement);
    setPinned(next);
  };
  const onLeft = useCallback((id: number) => { setLeaving((l) => (l?.txn.id === id ? null : l)); }, []);

  // After an action from a key, a chip, a swipe or the menu, focus goes to the new card; after a bottom button it stays
  // on that button. Out of cards, it goes to "All caught up", else to ↶ Undo (engineering choice 16). Nothing on load.
  useEffect(() => {
    if (!focusCard.current) return;
    focusCard.current = false;
    const el = pinned
      ? stage.current?.querySelector<HTMLElement>('[data-role="current"]')
      : document.querySelector<HTMLElement>('.review__done, .rtop__undo');
    el?.focus({ preventScroll: true });
  }, [pinned?.id, seenBack]);

  if (!current && !leaving) return null;
  const cards: { txn: Txn; role: CardRole }[] = [];
  if (leaving) cards.push({ txn: leaving.txn, role: 'leaving' });
  if (current) cards.push({ txn: current, role: 'current' });
  if (next) cards.push({ txn: next, role: 'next' });
  const guess = current?.guess ?? null;
  const rightLabel = elsewhere ? C.NEXT : guess ? label(guess) : C.ALL_CATEGORIES;
  const picks = current ? chipsFor(guess, chips).length : 0;

  return (
    <div className="focus">
      <div ref={stage} className="focus__stage">
        {cards.map(({ txn, role }) => (
          <FocusCard key={txn.id} txn={txn} chips={chips} today={today} role={role} swipe={swipe} demo={txn.id === demoFor}
            leave={role === 'leaving' && leaving ? leaving.how : null} elsewhere={role === 'current' && elsewhere}
            undone={undone?.id === txn.id ? undone.seq : null} busy={busy} fine={fine} controls={controls}
            onBegin={begin} onDone={finish} onFail={fail} onNote={onNote} onNext={moveNext} onLeft={onLeft} />
        ))}
      </div>
      {current && (
        <div ref={bar} className="focus__bar" data-testid="focus-bar">
          <Button variant="quiet" className="focus__snooze" busy={busy} disabled={elsewhere} aria-keyshortcuts={fine ? 'S' : undefined}
            onClick={() => { controls.current?.snooze(); }}>
            <span aria-hidden="true">‹ </span>{SKIP_FOR_NOW}
          </Button>
          <Button className="focus__take" busy={busy} aria-keyshortcuts={fine ? 'Enter' : undefined}
            onClick={() => { if (elsewhere) moveNext(); else controls.current?.take(); }}>
            {rightLabel}<span aria-hidden="true"> ›</span>
          </Button>
        </div>
      )}
      {current && fine && (
        <p className="focus__keys muted" data-testid="focus-keys" aria-hidden="true">
          <kbd>Enter</kbd> {rightLabel} · <kbd>{picks > 1 ? `1–${picks}` : '1'}</kbd> {C.KEY_PICK} · <kbd>S</kbd> {C.KEY_SNOOZE}
          {' · '}<kbd>I</kbd> {C.KEY_IGNORE}{household && <>{' · '}<kbd>B</kbd> {C.KEY_BUSINESS}</>}
          {' · '}<kbd>Z</kbd> {C.KEY_UNDO}{household && <>{' · '}<kbd>N</kbd> {C.KEY_NOTE}</>}
        </p>
      )}
      {current && !fine && coarse && swipe && hint && <p className="focus__hint muted" data-testid="focus-hint">{C.SWIPE_HINT}</p>}
    </div>
  );
}
