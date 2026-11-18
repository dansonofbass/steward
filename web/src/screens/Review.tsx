import { useQueryClient } from '@tanstack/react-query';
import { Suspense, useCallback, useEffect, useLayoutEffect, useMemo, useReducer, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useRedMonth } from '../api/home';
import { useMe, useReview, useUsual } from '../api/hooks';
import type { SortManyReply, Txn } from '../api/types';
import { useCanEdit, useIsHousehold } from '../book/BookContext';
import { Link } from '../book/links';
import {
  ALL_SORTED, ALL_SORTED_CHEER, ALL_SORTED_NOTE, BUSINESS_Q_N, DUPLICATES_N, MILESTONE, NO_CATEGORY_YET, ONE_DUPLICATE, REVIEW,
  REVIEW_EMPTY_BOOK, REVIEW_PICK, SELECT, SETTLE, SORTED_BY_STEWARD_N, SORTED_TODAY, TRY_AGAIN, VIEWER_CANT_CHANGE,
} from '../lib/copy';
import { BackgroundLine } from './home/BackgroundLine';
import { celebrationsOn, soundOn, withCelebrate } from '../lib/celebrations';
import { freshCheers, nextLine, rollGolden, sortCheer, type CheerState } from '../lib/lines';
import { isFee, momentAllowed } from '../lib/momentAllowed';
import { readView, saveView, type ReviewView } from '../lib/reviewPrefs';
import { useLongPress, useSelection } from '../lib/selection';
import { addSorts, NO_RUN, runAfter } from '../lib/sorts';
import { Acorn } from '../ui/Acorn';
import { BackToSetup } from '../ui/BackToSetup';
import { Button } from '../ui/Button';
import { useSayShown } from '../ui/Live';
import { Notice } from '../ui/Notice';
import { Rich } from '../ui/Rich';
import { Skeleton } from '../ui/Skeleton';
import { UndoToast } from '../ui/UndoToast';
import { useAcornMotion } from '../ui/useMoment';
import { BulkSort } from './bulk/load';
import { BusinessQuestions } from './review/BusinessQuestions';
import { Duplicates } from './review/Duplicates';
import { Focus } from './review/focus/load';
import { ignoreKey } from './review/keys';
import { ReviewCard, SNOOZE_HINT_ID } from './review/ReviewCard';
import { SlimRow } from './review/SlimRow';
import { SortCheer } from './review/SortCheer';
import { ignoreToast, plainToast, snoozeToast, sortToast, type ToastCheer } from './review/toastText';
import { TopBar } from './review/TopBar';
import type { Entry } from './review/undoStack';
import type { ActKind, Done } from './review/useReviewActions';
import { useVisit } from './review/useVisit';
import { undoOf, visitReducer } from './review/visitList';
import './review.css';

const refresh = (qc: ReturnType<typeof useQueryClient>) => { for (const key of ['review', 'spending']) void qc.invalidateQueries({ queryKey: [key] }); };

export default function Review() {
  const q = useReview();
  const canEdit = useCanEdit();
  const parent = !useIsHousehold();
  // Claim T6: no sort cheer in a red month, nor while Steward doesn't know the month (a parent book never cheers a sort).
  const red = useRedMonth(!parent) ?? true;
  const cheers = useRef<CheerState | null>(null);        // spec 3.7: every 3rd to 5th sort this visit
  const qc = useQueryClient();
  useUsual();   // warm the category menu's "Your usual" before the first More…
  const today = useMemo(() => new Date(), []);
  const me = useMe();
  const userId = me.data?.user.id ?? null;
  const [chosen, setChosen] = useState<ReviewView | null>(null);
  const [missing, setMissing] = useState(false);       // the Focus chunk couldn't load: the list, this visit
  // P1: per person on this device, focus by default; P3: a viewer gets the list only.
  const view: ReviewView = !canEdit || missing ? 'list' : chosen ?? readView(userId);
  const [back, setBack] = useState<{ txn: Txn; seq: number } | null>(null);
  const backSeq = useRef(0);
  const viewRef = useRef<ReviewView>(view);
  viewRef.current = view;
  const [rows, act] = useReducer(visitReducer, []);
  const rowsRef = useRef(rows);
  rowsRef.current = rows;
  const run = useRef(NO_RUN);
  const rose = useRef(false);
  const [sortedToday, setSortedToday] = useState<number | null>(null);   // null until this visit sorts something
  // Opened from the first run (guided setup spec 2.4): Back to setup shows after five sorts, or at once with none left.
  const fromWelcome = useSearchParams()[0].get('from') === 'welcome';
  const [sorts, setSorts] = useState(0);
  // Phase 17 (2.7): with motion off, Ten in a row and the milestones stay as words under the top bar, announced; the next
  // sort without a moment clears them. With motion on they pop as before (the pop is a status itself).
  const [said, setSaid] = useState<string | null>(null);
  const pop = useCallback((text: string | null) => {
    if (celebrationsOn()) { if (text) void withCelebrate((m) => { m.pop(text); }); return; }
    setSaid(text);
  }, []);

  // Review focus P20: nothing below an acted card moves. `keepBelow(id)` notes the first row below the card's bottom
  // edge (the next grid row) and its top; after the swap the page scrolls by what that row moved, in the same frame.
  // `keepAt(id?)` notes the card pressed, else the first whose top is on screen (Select changes every card's height).
  // One read before, one after; no listener. Near the top of the page window.scrollBy scrolls what there is.
  const place = useRef<{ id: string; top: number } | null>(null);
  const rowEls = () => [...document.querySelectorAll<HTMLElement>('.rcards > [data-id]')];
  const keepAt = useCallback((id?: number) => {
    const els = rowEls();
    const at = (id !== undefined && els.find((c) => c.dataset.id === String(id)))
      || els.find((c) => c.getBoundingClientRect().top >= 0) || els.find((c) => c.getBoundingClientRect().bottom > 0);
    place.current = at ? { id: at.dataset.id ?? '', top: at.getBoundingClientRect().top } : null;
  }, []);
  const keepBelow = useCallback((id: number) => {
    const els = rowEls();
    const me = els.find((c) => c.dataset.id === String(id));
    const bottom = me?.getBoundingClientRect().bottom;
    const below = me && bottom !== undefined ? els.find((c) => c !== me && c.getBoundingClientRect().top >= bottom - 1) : undefined;
    place.current = below ? { id: below.dataset.id ?? '', top: below.getBoundingClientRect().top } : null;
  }, []);
  useLayoutEffect(() => {
    const p = place.current;
    if (!p) return;
    place.current = null;
    const el = document.querySelector<HTMLElement>(`.rcards > [data-id="${p.id}"]`);
    const by = el ? el.getBoundingClientRect().top - p.top : 0;
    if (by !== 0) window.scrollBy(0, by);
  });

  const visit = useVisit(useCallback((e: Entry, card: Txn | null) => {
    run.current = NO_RUN;                  // any Undo breaks the run (P18)
    if (e.kind === 'note') return;
    if (viewRef.current === 'focus') {     // the card returns as the current one (P15)
      if (card) setBack({ txn: card, seq: ++backSeq.current });
      return;
    }
    if (e.kind === 'bulk') keepAt(); else keepBelow(e.ids[0]);
    // The slim rows grow back into their cards, in place; a card acted on in focus comes back at the list's end.
    act({ type: 'restore', entry: e.id, card: card ?? undefined });
  }, [keepAt, keepBelow]));
  const { begin, done, fail, say, undo, forget } = visit;
  const left = useRef(visit.left);
  left.current = visit.left;

  const counted = useCallback((n: number): string | null => {
    const { tally, milestone } = addSorts(n);
    setSortedToday(tally.today);
    return milestone !== null ? MILESTONE.replace('{n}', milestone.toLocaleString('en-US')) : null;
  }, []);
  const onBegin = useCallback((txn: Txn, kind: ActKind) => begin(kind, txn, viewRef.current), [begin]);
  const onFail = useCallback((entry: string) => { fail(entry); }, [fail]);
  const onDone = useCallback((txn: Txn, entry: string, d: Done) => {
    const inList = viewRef.current === 'list';
    if (inList) keepBelow(txn.id);
    setSorts((n) => n + 1);
    if (d.kind === 'sort') {
      const category = d.reply.result?.category ?? d.category;
      done(entry, d.reply.result?.undo ?? null, [txn.id, ...d.ids], true);
      const milestone = counted(1 + d.applied);
      const r = runAfter(run.current, 'sort');
      run.current = r.run;
      pop(milestone ?? r.label);
      const allowed = momentAllowed('sort', { parent, red, fee: isFee(category) });
      let cheer: ToastCheer | null = null;
      if (allowed.line) {
        const draw = sortCheer(cheers.current ?? freshCheers(), d.applied, allowed.golden);
        cheers.current = draw.next;
        if (draw.line) cheer = { line: draw.line, golden: draw.golden };
      }
      say(entry, { ...sortToast(txn, d), cheer });
      if (inList) act({ type: 'acted', id: txn.id, outcome: { kind: 'sorted', category, n: d.applied, entry }, matched: { ids: d.ids, category } });
    } else {
      done(entry, d.reply.undo, [txn.id], true);
      run.current = NO_RUN;
      say(entry, d.kind === 'snooze' ? snoozeToast(d.reply.until, today) : ignoreToast(txn));
      if (inList) {
        act({ type: 'acted', id: txn.id, outcome: d.kind === 'snooze' ? { kind: 'snoozed', until: d.reply.until, entry } : { kind: 'ignored', entry } });
      }
    }
    refresh(qc);
  }, [done, say, counted, keepBelow, qc, today, pop, parent, red]);
  const undoOne = useCallback((entry: string) => { void undo(entry); }, [undo]);
  const undoTop = useCallback(() => { void undo(); }, [undo]);

  // Z steps back one action, in either view (keys never fire while typing, in a dialog or with a modifier).
  useEffect(() => {
    if (!canEdit) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key.toLowerCase() !== 'z' || ignoreKey(e, { busy: false, menuOpen: false })) return;
      e.preventDefault();
      undoTop();
    };
    document.addEventListener('keydown', onKey);
    return () => { document.removeEventListener('keydown', onKey); };
  }, [canEdit, undoTop]);

  // The list's rows: the queue as it was when the list opened, then each refetch (visitList keeps outcomes and order).
  const data = q.data;
  useLayoutEffect(() => {
    if (!data || view !== 'list') return;
    act({ type: 'sync', queue: data.uncategorized.filter((t) => !left.current.has(t.id)) });
  }, [data, view]);

  // Bulk sort (profile spec): Select, then a click picks a card. The sorted cards become slim rows, and the bar's token
  // goes on the stack too, so ↶ and Z can undo it.
  const sel = useSelection(() => rowsRef.current.filter((r) => r.outcome.kind === 'waiting').map((r) => r.id));
  const [bulk, setBulk] = useState(false);
  const selectBtn = useRef<HTMLButtonElement>(null);
  const { start: selStart, end: selEnd, keep: selKeep } = sel;
  const startSelect = useCallback((first?: number) => { keepAt(first); setBulk(true); selStart(first); }, [keepAt, selStart]);
  const endSelect = useCallback(() => { keepAt(); selEnd(); }, [keepAt, selEnd]);
  const press = useLongPress(canEdit && !sel.on ? startSelect : null);
  const onBulkSorted = useCallback((r: SortManyReply) => {
    if (r.skipped.length) selKeep(r.skipped.map((x) => x.id)); else endSelect();
    if (r.sorted === 0 || !r.undo) return;
    const entry = begin('bulk', null, 'list');
    done(entry, r.undo, r.ids, true);
    act({ type: 'bulk', ids: r.ids, category: r.category, entry });
    setSorts((n) => n + r.sorted);
    pop(counted(r.sorted));
    refresh(qc);
  }, [begin, done, counted, endSelect, selKeep, qc, pop]);
  const onBulkUndone = useCallback((r: SortManyReply) => { if (r.undo) forget(r.undo); refresh(qc); }, [forget, qc]);
  // A note saved or removed on a card (either view) is a stack entry like the others; its Undo leaves the card where it is.
  const onNote = useCallback((txn: Txn, token: string, text: string) => {
    const entry = begin('note', txn, viewRef.current);
    done(entry, token, [txn.id], false);
    say(entry, plainToast(text));
  }, [begin, done, say]);
  const onMissing = useCallback(() => { setMissing(true); }, []);
  // Switching saves the view and clears the list's slim rows (decision 9); the stack stays.
  const setView = useCallback((v: ReviewView) => {
    if (v === viewRef.current) return;     // the view you are in: nothing to switch, and no cards to drop
    saveView(userId, v);
    setChosen(v);
    act({ type: 'clear' });
    selEnd();
  }, [userId, selEnd]);
  const onCaughtUp = useCallback((el: HTMLElement) => {
    if (rose.current) return;            // once per visit
    rose.current = true;
    void withCelebrate((c) => { c.sunrise(el); });
  }, []);

  if (q.isError) {
    return (
      <div className="screen review">
        <Notice tone="error">
          <p>{q.error.message}</p>
          <Button variant="quiet" onClick={() => void q.refetch()}>{TRY_AGAIN}</Button>
        </Notice>
      </div>
    );
  }
  if (!q.data || me.isPending) {
    return (
      <div className="screen review" aria-busy="true">
        <div className="rcards">{[0, 1, 2].map((i) => <div className="card" key={i}><Skeleton lines={3} /></div>)}</div>
      </div>
    );
  }

  const { uncategorized, count, duplicates, duplicate_count, top_categories } = q.data;
  const sorted = q.data.sorted_count ?? 0;
  const fresh = uncategorized.filter((t) => !visit.left.has(t.id));
  const nLeft = Math.max(0, count - (uncategorized.length - fresh.length));
  const business = q.data.business_count ?? 0;
  const waitingRows = rows.filter((r) => r.outcome.kind === 'waiting');
  const pickedIds = sel.on ? waitingRows.filter((r) => sel.ids.has(r.id)).map((r) => r.id) : [];
  const caughtUp = nLeft + business === 0 && duplicate_count === 0 && fresh.length === 0;
  // Review focus P25: "N left" in the top bar says what the first two parts said; the rest of the line stays.
  const parts = [
    business > 0 && BUSINESS_Q_N.replace('{n}', String(business)),
    duplicate_count > 0 && (duplicate_count === 1 ? ONE_DUPLICATE : DUPLICATES_N.replace('{n}', String(duplicate_count))),
  ].filter((p): p is string => Boolean(p));
  const t = visit.toast;
  const gone = visit.left.size;
  const progress = view === 'focus' ? (gone + nLeft > 0 ? gone / (gone + nLeft) : 0) : null;
  const inStack = new Set(visit.stack.map((e) => e.id));   // a slim row offers Undo only while its entry can be undone

  return (
    <div className={`screen review${sel.on ? ' is-selecting' : ''}`}>
      {fromWelcome && (sorts >= 5 || caughtUp) && <BackToSetup step="extras" />}
      <header className="page-head">
        <h1>{REVIEW}</h1>
        {(parts.length > 0 || sorted > 0) && (
          <p className="review__counts" data-testid="review-counts">
            {parts.map((p, i) => <span key={i}>{p}</span>)}
            {sorted > 0 && <span><Link className="review__sorted" to="/transactions?sorted=steward&dates=all">{SORTED_BY_STEWARD_N.replace('{n}', String(sorted))}</Link></span>}
          </p>
        )}
      </header>
      {q.data.background && <BackgroundLine bg={q.data.background} className="review__background muted" testId="review-background" />}
      {(nLeft > 0 || visit.stack.length > 0) && (
        <TopBar left={nLeft} undo={canEdit ? { can: visit.stack.length > 0, busy: visit.undoing, run: undoTop } : undefined}
          view={canEdit ? { is: view, set: setView } : undefined} progress={progress} />
      )}
      {/* Always mounted, so a screen reader is already listening when the words arrive (NVDA and JAWS skip a live
          region that mounts with its text). Empty, it takes no space. */}
      <p className="review__said" role="status" aria-live="polite" data-testid="review-said">{said ?? ''}</p>
      {caughtUp && <CaughtUp empty={q.data.empty === true} cheer={sortedToday !== null} today={sortedToday ?? 0} onShown={onCaughtUp} parent={parent} />}
      {!canEdit && <Notice>{VIEWER_CANT_CHANGE}</Notice>}
      <fieldset className="readonly" disabled={!canEdit}>
        {view === 'focus' && (
          <Suspense fallback={<div className="focus" aria-busy="true"><div className="card fcard"><Skeleton lines={4} /></div></div>}>
            <Focus rows={fresh} chips={top_categories} today={today} back={back} onBegin={onBegin} onDone={onDone}
              onFail={onFail} onNote={onNote} onMissing={onMissing} />
          </Suspense>
        )}
        {view === 'list' && rows.length > 0 && (
          <section className="stack" aria-labelledby="rv-none-h">
            <div className="stack stack--tight">
              <div className="review__list-head">
                <h2 id="rv-none-h">{NO_CATEGORY_YET}</h2>
                {canEdit && waitingRows.length > 0 && (
                  <button ref={selectBtn} type="button" className={`filter${sel.on ? ' is-on' : ''}`} aria-pressed={sel.on}
                    onClick={() => { if (sel.on) endSelect(); else startSelect(); }}>{SELECT}</button>
                )}
              </div>
              <p className="muted" id={SNOOZE_HINT_ID}>{REVIEW_PICK}</p>
            </div>
            <div className="rcards" {...press}>
              {rows.map((r) => (r.outcome.kind === 'waiting'
                ? <ReviewCard key={r.id} txn={r.txn} chips={top_categories} today={today} back={r.back} onBegin={onBegin} onDone={onDone}
                    onFail={onFail} onNote={onNote} selecting={sel.on} picked={sel.ids.has(r.id)} onPick={sel.pick} />
                : <SlimRow key={`slim-${r.id}`} row={r} today={today} undoable={inStack.has(undoOf(r.outcome) ?? '')} onUndo={undoOne} />))}
            </div>
          </section>
        )}
        <Duplicates pairs={duplicate_count > 0 ? duplicates : []} today={today} />
        <BusinessQuestions rows={q.data.business ?? []} today={today} />
      </fieldset>
      {bulk && (
        <Suspense fallback={null}>
          <BulkSort selecting={sel.on} ids={pickedIds} onCancel={endSelect} onSorted={onBulkSorted} onUndone={onBulkUndone} home={() => selectBtn.current} />
        </Suspense>
      )}
      {t && (
        <UndoToast key={t.key} tag={t.body.tag} text={<Rich parts={t.body.parts} />}
          cheer={t.body.cheer ? <SortCheer cheer={t.body.cheer} /> : null}
          link={t.body.settle ? <Link className="link" to={`/spending/reimbursements?settle=${t.body.settle.id}`}>{SETTLE}</Link> : null}
          onUndo={t.entry ? () => { undoOne(t.entry!); } : undefined} onClose={visit.closeToast} lifted={view !== 'list'} />
      )}
    </div>
  );
}

/** "All caught up" (roadmap 12; phase 17 spec 3.7): a real resting place. The resting acorn dozes on a small horizon,
 *  with a caughtUp line, golden about 1 in 40. After this visit sorted something, the spec's cheer and the day's count, with the
 *  sunrise (choice 15). Focus moves here when the last card goes (review focus P30). A book with no transactions at all
 *  isn't caught up: it says so, with no cheer and no sunrise (phase 17, 2.7). */
function CaughtUp({ empty, cheer, today, onShown, parent }: { empty: boolean; cheer: boolean; today: number; onShown: (el: HTMLElement) => void; parent: boolean }) {
  const el = useRef<HTMLDivElement>(null);
  const svg = useRef<SVGSVGElement>(null);
  const allowed = momentAllowed('caughtUp', { parent });
  const [golden] = useState(() => !empty && allowed.golden && rollGolden());
  const [line] = useState(() => (empty || !allowed.line ? null : nextLine(golden ? 'goldenSort' : 'caughtUp')));
  useAcornMotion(svg, !empty && allowed.motion ? (golden ? 'golden' : 'doze') : null, cheer && allowed.sound && soundOn());
  useEffect(() => { if (cheer && !empty && el.current) onShown(el.current); }, [cheer, empty, onShown]);
  // Said through the page's polite region, not a live region of its own: one that appears with its words in it is
  // often not read (issue #23).
  useSayShown(el);
  return (
    <div ref={el} className="review__done" tabIndex={-1}>
      {empty ? <p className="review__done-title">{REVIEW_EMPTY_BOOK}</p> : (
        <>
          {allowed.face && <span className="review__horizon" aria-hidden="true"><Acorn ref={svg} face={golden ? 'golden' : 'resting'} size={56} /></span>}
          <p className="review__done-title">{cheer ? ALL_SORTED_CHEER : ALL_SORTED}</p>
          {line && <p className="review__done-line" data-testid="caught-up-line">{line}</p>}
          <p className="muted">{cheer ? SORTED_TODAY.replace('{n}', String(today)) : ALL_SORTED_NOTE}</p>
        </>
      )}
    </div>
  );
}
