import { Sprout } from 'lucide-react';
import { Suspense, useState } from 'react';
import { currentBook } from '../../api/book';
import { redMonth, type HomeData } from '../../api/home';
import { Link } from '../../book/links';
import { celebrationsOn } from '../../lib/celebrations';
import { dollars } from '../../lib/format';
import { headline, ordinal } from '../../lib/headline';
import { momentAllowed } from '../../lib/momentAllowed';
import { phaseFor } from '../../lib/sky';
import { Skeleton } from '../../ui/Skeleton';
import { FIG_BLACK, FIG_EVEN, FIG_NOTHING, FIG_RED, GREETING, GREETING_LATE, JOY, LEGEND_IN, LEGEND_OUT, PAYDAY } from './copy';
import { PaydayMoment } from './lazyMoments';

const BEST_KEY = 'steward-home-best';
const FLOOR = 2;
const DAY_LINE = new Intl.DateTimeFormat('en-US', { weekday: 'long', month: 'short', day: 'numeric' });

/** P41: "Friday, Oct 30", from the server's day (as_of), never the browser's clock. */
export function dayLine(asOf: string): string {
  const [y, m, d] = asOf.split('-').map(Number);
  return DAY_LINE.format(new Date(y, m - 1, d));
}

/** The bar's two widths in percent: in / (in + out) and the rest, a side with money at least 2% wide. Null when
 *  nothing came in or went out. */
export function barWidths(inCents: number, outCents: number): { in: number; out: number } | null {
  const total = inCents + outCents;
  if (total <= 0) return null;
  let share = (inCents / total) * 100;
  if (inCents > 0) share = Math.max(FLOOR, share);
  if (outCents > 0) share = Math.min(100 - FLOOR, share);
  return { in: share, out: 100 - share };
}

function firstShowThisMonth(month: string): boolean {
  try {
    if (localStorage.getItem(BEST_KEY) === month) return false;
    localStorage.setItem(BEST_KEY, month);
    return true;
  } catch {
    return false;                                   // private mode: the line shows, still
  }
}

/** P40: a quiet line on a very good month. It fades in the first time it shows in a month on this device, and is
 *  static under reduced motion or with Celebrations off. No sound, no burst. */
function Joy({ month }: { month: string }) {
  const [fresh] = useState(() => celebrationsOn() && firstShowThisMonth(month));
  return (
    <p className={`verdict__joy${fresh ? ' is-new' : ''}`} data-testid="joy">
      <Sprout className="i" size={20} aria-hidden="true" />{JOY}
    </p>
  );
}

/** Money in minus money out so far this month, in words (the colour is never the only signal), the bar and its
 *  legend (P3-P7). */
function Figure({ flow }: { flow: HomeData['flow'] }) {
  const { in_cents: inCents, out_cents: outCents, net_cents: net } = flow;
  const bar = barWidths(inCents, outCents);
  if (bar === null) return <p className="verdict__figure is-nothing" data-testid="figure">{FIG_NOTHING}</p>;
  const words = net > 0 ? FIG_BLACK : net < 0 ? FIG_RED : null;
  return (
    <>
      <p className={`verdict__figure ${net < 0 ? 'is-red' : 'is-black'}`} data-testid="figure">
        {words === null ? FIG_EVEN : <><span className="verdict__amount">{dollars(Math.abs(net))}</span>{words.replace('{amount}', '')}</>}
      </p>
      <span className="verdict__bar" aria-hidden="true">
        <span className="verdict__in" style={{ width: `${bar.in}%` }} />
        <span className="verdict__out" style={{ width: `${bar.out}%` }} />
      </span>
      <span className="verdict__legend">
        <span>{LEGEND_IN.replace('{amount}', dollars(inCents))}</span>
        <span>{LEGEND_OUT.replace('{amount}', dollars(outCents))}</span>
      </span>
    </>
  );
}

/** Spec 3.7: the greeting word from the sky phase on the device's clock, as the sky reads it. */
export function greeting(now: Date = new Date()): string {
  const phase = phaseFor(now);
  return phase === 'night' && now.getHours() < 5 ? GREETING_LATE : GREETING[phase];
}

const PAYDAY_KEY = 'steward-payday';
/** 'fresh' on the visit the usual pay landed since the last look (the coins play), 'again' for the rest of that day
 *  (the line stays, still), else null. Kept per book on this device. */
export function paydayMoment(book: string, asOf: string, came: boolean): 'fresh' | 'again' | null {
  const key = `${PAYDAY_KEY}:${book}`;
  try {
    if (came) { localStorage.setItem(key, asOf); return 'fresh'; }
    return localStorage.getItem(key) === asOf ? 'again' : null;
  } catch {
    return came ? 'fresh' : null;
  }
}

const usually = (d: HomeData) => d.flow.payday && <p className="verdict__payday muted">{PAYDAY.replace('{day}', ordinal(d.flow.payday.day))}</p>;

/** The usual payday's line, or the payday moment in its place for the day the pay landed. */
function Payday({ data }: { data: HomeData }) {
  const [pay] = useState(() => paydayMoment(currentBook() ?? '', data.as_of, (data.flow.payday_came ?? null) !== null));
  if (pay) return <Suspense fallback={null}><PaydayMoment fresh={pay === 'fresh'} /></Suspense>;
  return usually(data) || null;
}

/** How are we doing? (Home spec, section 1): the date line, the headline (the page's h1), and, unless the book is
 *  empty, the figure block (it opens Spending on this month), the usual payday when it hasn't come, and joy. */
export function Verdict({ data, ready }: { data?: HomeData; ready: boolean }) {
  if (!data) {
    return (
      <section className="verdict" aria-busy="true">
        <Skeleton lines={2} />
        <Skeleton lines={1} />
        <div className="signs">{[0, 1, 2, 3].map((i) => <div key={i} className="sign"><Skeleton lines={2} /></div>)}</div>
      </section>
    );
  }
  const empty = data.verdict.opener === 'empty';
  const red = redMonth(data);
  return (
    <section className="verdict" data-testid="verdict" data-ready={ready ? 'true' : undefined} aria-labelledby="verdict-h">
      <p className="verdict__date">{dayLine(data.as_of)}{momentAllowed('greeting', { parent: false, red }).line && <span className="verdict__greet"> · {greeting()}</span>}</p>
      <h1 id="verdict-h" className="verdict__headline">{headline(data.verdict)}</h1>
      {!empty && <Link className="verdict__flow" to={`/spending?month=${data.month}`}><Figure flow={data.flow} /></Link>}
      {!empty && (momentAllowed('payday', { parent: false, red }).line ? <Payday data={data} /> : usually(data))}
      {!empty && data.verdict.best_month && <Joy month={data.month} />}
    </section>
  );
}
